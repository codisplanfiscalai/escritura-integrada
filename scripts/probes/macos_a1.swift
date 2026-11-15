// Native capability probe only: never imported by the app, no fiscal endpoints.
import Foundation
import Security

func stop(_ code: String, _ status: Int32 = 1) -> Never {
    print("{\"ok\":false,\"code\":\"\(code)\"}")
    exit(status)
}
struct Input: Decodable {
    let pfx: String
    let password: String
    let expectedDER: String
    let ca: String
    let port: Int
    let presentClient: Bool
}
let input: Input
 do {
    input = try JSONDecoder().decode(Input.self, from: FileHandle.standardInput.readDataToEndOfFile())
} catch { stop("probe_input") }
guard input.port > 0 && input.port <= 65535 else { stop("probe_port") }
guard #available(macOS 15.0, *) else { stop("probe_os") }
let blob: Data
 do { blob = try Data(contentsOf: URL(fileURLWithPath: input.pfx)) }
 catch { stop("probe_pfx_read") }
var items: CFArray?
let options: [String: Any] = [kSecImportExportPassphrase as String: input.password,
                             kSecImportToMemoryOnly as String: true]
let status = SecPKCS12Import(blob as CFData, options as CFDictionary, &items)
guard status == errSecSuccess else { stop("probe_identity_import_status_\(status)",10) }
guard let imported = items as? [[String: Any]] else { stop("probe_identity_array",10) }
let identities = imported.compactMap { $0[kSecImportItemIdentity as String] }
guard identities.count == 1, let value = identities.first else { stop("probe_identity_count_\(identities.count)",10) }
let identity = value as! SecIdentity
var leaf: SecCertificate?
guard SecIdentityCopyCertificate(identity, &leaf) == errSecSuccess, let certificate = leaf,
      Data(base64Encoded: input.expectedDER) == (SecCertificateCopyData(certificate) as Data) else { stop("probe_leaf_mismatch") }
// Synthetic probe instrumentation only; never logs an operator credential.
let fields = [kSecOIDSubjectAltName, kSecOIDX509V1ValidityNotBefore, kSecOIDX509V1ValidityNotAfter]
if let properties = SecCertificateCopyValues(certificate, fields as CFArray, nil) {
    print("synthetic_certificate_properties=\(properties)")
}
// The synthetic certificate has a random unique CN; memory-only import must not
// leave that certificate in the default keychain. Only its synthetic label is queried.
guard let label = SecCertificateCopySubjectSummary(certificate) as String? else { stop("probe_subject") }
var persisted: CFTypeRef?
let query: [String: Any] = [kSecClass as String: kSecClassCertificate,
                          kSecAttrLabel as String: label, kSecReturnRef as String: true]
let persistedStatus = SecItemCopyMatching(query as CFDictionary, &persisted)
guard persistedStatus == errSecItemNotFound else { stop("probe_keychain_persistence") }
let caData: Data
 do { caData = try Data(contentsOf: URL(fileURLWithPath: input.ca)) }
 catch { stop("probe_ca_read") }
guard let anchor = SecCertificateCreateWithData(nil, caData as CFData) else { stop("probe_ca") }

final class Delegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    let identity: SecIdentity
    let anchor: SecCertificate
    let present: Bool
    init(_ identity: SecIdentity, _ anchor: SecCertificate, _ present: Bool) {
        self.identity = identity; self.anchor = anchor; self.present = present
    }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust {
            guard let trust = challenge.protectionSpace.serverTrust,
                  SecTrustSetAnchorCertificates(trust, [anchor] as CFArray) == errSecSuccess,
                  SecTrustSetAnchorCertificatesOnly(trust, true) == errSecSuccess,
                  SecTrustEvaluateWithError(trust, nil) else {
                completionHandler(.cancelAuthenticationChallenge, nil); return
            }
            // Probe-only trust anchor: validates the synthetic CA and hostname.
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodClientCertificate && present {
            completionHandler(.useCredential, URLCredential(identity: identity, certificates: nil, persistence: .forSession))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
let configuration = URLSessionConfiguration.ephemeral
configuration.httpCookieStorage = nil
configuration.urlCredentialStorage = nil
configuration.urlCache = nil
configuration.connectionProxyDictionary = [:]
configuration.tlsMinimumSupportedProtocolVersion = .TLSv12
configuration.timeoutIntervalForRequest = 5
configuration.timeoutIntervalForResource = 10
let delegate = Delegate(identity, anchor, input.presentClient)
let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
let semaphore = DispatchSemaphore(value: 0)
var success = false
let url = URL(string: "https://127.0.0.1:\(input.port)/probe")!
let task = session.dataTask(with: url) { data, response, error in
    success = error == nil && (response as? HTTPURLResponse)?.statusCode == 200 && data == Data("synthetic-mtls-ok".utf8)
    semaphore.signal()
}
task.resume()
guard semaphore.wait(timeout: .now() + 15) == .success else { session.invalidateAndCancel(); stop("probe_timeout") }
session.invalidateAndCancel()
guard success else { stop("probe_tls_rejected",20) }
print("{\"ok\":true,\"memory_only_identity\":true,\"leaf_der_match\":true,\"local_mtls\":true}")
