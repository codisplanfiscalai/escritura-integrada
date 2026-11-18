// Read-only A1 helper for Escritura Integrada, macOS 15+, private stdin/stdout IPC.
// No key export, keychain persistence, user URLs, issuance or fiscal event APIs.
import Foundation
import Security
import CryptoKit
import CFNetwork

let protocolVersion = 1
let maxBody = 20 * 1024 * 1024
#if RECEPTION_TESTING
let buildKind = "testing"
#else
let buildKind = "production"
#endif

func output(_ values: [String: Any], code: Int32 = 0) -> Never {
    let object = values.merging(["protocol": protocolVersion, "build": buildKind]) { _, new in new }
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { exit(2) }
    FileHandle.standardOutput.write(data)
    exit(code)
}
func fail(_ code: String) -> Never { output(["ok": false, "code": code], code: 1) }
func digits(_ value: String, _ minimum: Int, _ maximum: Int) -> Bool {
    let bytes = Array(value.utf8)
    return bytes.count >= minimum && bytes.count <= maximum && bytes.allSatisfy { $0 >= 48 && $0 <= 57 }
}
func validCNPJ(_ value: String) -> Bool {
    let bytes = Array(value.utf8)
    guard bytes.count == 14, Set(bytes).count > 1,
          bytes.prefix(12).allSatisfy({ (48...57).contains($0) || (65...90).contains($0) }),
          bytes.suffix(2).allSatisfy({ (48...57).contains($0) }) else { return false }
    // RFB: ASCII code minus 48, including A=17, B=18 ... Z=42.
    let d = bytes.map { Int($0) - 48 }
    func check(_ weights: [Int], _ position: Int) -> Bool {
        let remainder = zip(d,weights).reduce(0) { $0 + $1.0 * $1.1 } % 11
        return d[position] == (remainder < 2 ? 0 : 11 - remainder)
    }
    return check([5,4,3,2,9,8,7,6,5,4,3,2],12) && check([6,5,4,3,2,9,8,7,6,5,4,3,2],13)
}
var raw = Data()
while true {
    let chunk = FileHandle.standardInput.readData(ofLength: min(65536,8 * 1024 * 1024 + 1 - raw.count))
    if chunk.isEmpty { break }
    raw.append(chunk)
    if raw.count > 8 * 1024 * 1024 { fail("reception_credentials") }
}
guard raw.count <= 8 * 1024 * 1024,
      let input = (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any],
      let version = input["protocol"] as? NSNumber,
      CFGetTypeID(version) != CFBooleanGetTypeID(), version.intValue == protocolVersion,
      let action = input["action"] as? String else { fail("reception_operation") }
if action == "version" {
    guard Set(input.keys) == Set(["protocol","action"]) else { fail("reception_operation") }
    output(["ok":true])
}
guard #available(macOS 15.0, *) else { fail("reception_native_installation") }
var allowed = Set(["protocol","action","pfx_base64","password"])
if action == "query" {
    allowed.formUnion(["target","provider","environment","allow_procuration","expected_holder","certificate_sha256","last_nsu","uf_code"])
} else if action != "inspect" { fail("reception_operation") }
#if RECEPTION_TESTING
if action == "query" { allowed.formUnion(["test_port","test_ca_base64","test_present_client"]) }
#endif
guard Set(input.keys).isSubset(of: allowed),
      let encoded = input["pfx_base64"] as? String, encoded.utf8.count <= 6_666_672,
      let pfx = Data(base64Encoded: encoded), !pfx.isEmpty, pfx.count <= 5_000_000,
      let password = input["password"] as? String, !password.isEmpty, password.utf8.count <= 4096 else { fail("reception_credentials") }
var imported: CFArray?
let options: [String: Any] = [kSecImportExportPassphrase as String: password, kSecImportToMemoryOnly as String: true]
guard SecPKCS12Import(pfx as CFData, options as CFDictionary, &imported) == errSecSuccess,
      let items = imported as? [[String: Any]] else { fail("reception_credentials") }
let identities = items.filter { $0[kSecImportItemIdentity as String] != nil }
guard identities.count == 1, let item = identities.first,
      let object = item[kSecImportItemIdentity as String],
      CFGetTypeID(object as CFTypeRef) == SecIdentityGetTypeID() else { fail("reception_credentials") }
let identity = object as! SecIdentity
var leaf: SecCertificate?
guard SecIdentityCopyCertificate(identity,&leaf) == errSecSuccess, let certificate = leaf else { fail("reception_certificate_identity") }
let fields = [kSecOIDSubjectAltName,kSecOIDX509V1ValidityNotBefore,kSecOIDX509V1ValidityNotAfter]
guard let properties = SecCertificateCopyValues(certificate, fields as CFArray, nil) as? [String: Any],
      let san = properties[kSecOIDSubjectAltName as String] as? [String: Any],
      san[kSecPropertyKeyType as String] as? String == kSecPropertyTypeSection as String,
      let names = san[kSecPropertyKeyValue as String] as? [[String: Any]] else { fail("reception_certificate_identity") }
let holders = names.filter { $0[kSecPropertyKeyLabel as String] as? String == "2.16.76.1.3.3" }
guard holders.count == 1, let holderProperty = holders.first,
      holderProperty[kSecPropertyKeyType as String] as? String == kSecPropertyTypeString as String,
      let holder = holderProperty[kSecPropertyKeyValue as String] as? String,
      validCNPJ(holder) else { fail("reception_certificate_identity") }
func dateProperty(_ key: CFString) -> Double {
    guard let value = properties[key as String] as? [String: Any],
          value[kSecPropertyKeyType as String] as? String == kSecPropertyTypeNumber as String,
          let number = value[kSecPropertyKeyValue as String] as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite else { fail("reception_certificate_identity") }
    // SecCertificateCopyValues numbers use CFAbsoluteTime's 2001 reference epoch.
    return Date(timeIntervalSinceReferenceDate: number.doubleValue).timeIntervalSince1970
}
let notBefore = dateProperty(kSecOIDX509V1ValidityNotBefore)
let notAfter = dateProperty(kSecOIDX509V1ValidityNotAfter)
let stamp = Date().timeIntervalSince1970
guard notBefore <= stamp && stamp < notAfter else { fail("reception_certificate_expired") }
let der = SecCertificateCopyData(certificate) as Data
let fingerprint = SHA256.hash(data: der).map { String(format:"%02x",$0) }.joined()
let metadata: [String: Any] = ["ok":true,"holder_tax_id":holder,"certificate_sha256":fingerprint,
                               "not_before":notBefore,"not_after":notAfter]
if action == "inspect" { output(metadata) }
guard input["certificate_sha256"] as? String == fingerprint, input["expected_holder"] as? String == holder else { fail("reception_native_pin") }
guard let target = input["target"] as? String, validCNPJ(target),
      let provider = input["provider"] as? String,
      let environment = input["environment"] as? String,
      let number = input["last_nsu"] as? String,
      let allow = input["allow_procuration"] as? NSNumber, CFGetTypeID(allow) == CFBooleanGetTypeID() else { fail("reception_operation") }
var endpoint: String
var requestBody: Data? = nil
var method: String
var contentType: String? = nil
if provider == "nfse_adn" {
    // XML alphanumeric support is not proof of the ADN query parameter contract.
    guard digits(target,14,14), digits(holder,14,14) else { fail("reception_adn_alphanumeric_pending") }
    guard digits(number,15,19), let numeric = UInt64(number), numeric <= UInt64(Int64.max), input["uf_code"] == nil else { fail("reception_operation") }
    guard target.prefix(8) == holder.prefix(8) || allow.boolValue else { fail("reception_certificate_identity") }
    let endpoints = ["production":"https://adn.nfse.gov.br/contribuintes", "restricted_production":"https://adn.producaorestrita.nfse.gov.br/contribuintes"]
    guard let base = endpoints[environment] else { fail("reception_endpoint") }
    endpoint = base + "/DFe/" + number + "?cnpjConsulta=" + target + "&lote=true"
    method = "GET"
} else if provider == "nfe_distribution" {
    guard target.prefix(8) == holder.prefix(8), digits(number,15,15),
          let uf = input["uf_code"] as? String,
          Set(["11","12","13","14","15","16","17","21","22","23","24","25","26","27","28","29","31","32","33","35","41","42","43","50","51","52","53"]).contains(uf) else { fail("reception_certificate_identity") }
    let endpoints = ["production":"https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx", "homologation":"https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"]
    guard let base = endpoints[environment] else { fail("reception_endpoint") }
    endpoint = base; method = "POST"; contentType = "application/soap+xml; charset=utf-8"
    let amb = environment == "production" ? "1" : "2"
    let xml = """
    <?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"><nfeDadosMsg><distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>\(amb)</tpAmb><cUFAutor>\(uf)</cUFAutor><CNPJ>\(target)</CNPJ><distNSU><ultNSU>\(number)</ultNSU></distNSU></distDFeInt></nfeDadosMsg></nfeDistDFeInteresse></s:Body></s:Envelope>
    """
    requestBody = Data(xml.utf8)
} else { fail("reception_operation") }
#if RECEPTION_TESTING
let testOriginalEndpoint = endpoint
#endif
var testAnchor: SecCertificate? = nil
var presentClient = true
#if RECEPTION_TESTING
if let port = input["test_port"] as? Int {
    guard port > 0 && port <= 65535, let data = input["test_ca_base64"] as? String,
          let decoded = Data(base64Encoded: data), decoded.count <= 20000,
          let anchor = SecCertificateCreateWithData(nil, decoded as CFData) else { fail("reception_operation") }
    endpoint = "https://127.0.0.1:\(port)/probe"
    testAnchor = anchor
    presentClient = input["test_present_client"] as? Bool ?? true
}
#endif
guard let url = URL(string:endpoint), let host = url.host else { fail("reception_endpoint") }
let chain = (item[kSecImportItemCertChain as String] as? [SecCertificate] ?? []).filter { (SecCertificateCopyData($0) as Data) != der }

final class Receiver: NSObject, URLSessionDataDelegate {
    let identity: SecIdentity
    let certificates: [SecCertificate]
    let host: String
    let testAnchor: SecCertificate?
    let presentClient: Bool
    let done = DispatchSemaphore(value:0)
    let lock = NSLock()
    var bytes = Data()
    var status = 0
    var retry = 0
    var failure: String? = nil
    init(_ identity: SecIdentity, _ certificates: [SecCertificate], _ host: String,
         _ anchor: SecCertificate?, _ present: Bool) {
        self.identity=identity;self.certificates=certificates;self.host=host;self.testAnchor=anchor;self.presentClient=present
    }
    func reject(_ task: URLSessionTask, _ code: String) { lock.lock();failure=code;lock.unlock();task.cancel() }
    func challenge(_ challenge: URLAuthenticationChallenge, _ completion: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.host == host, challenge.previousFailureCount == 0 else {
            completion(.cancelAuthenticationChallenge,nil);return
        }
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodClientCertificate && presentClient {
            completion(.useCredential,URLCredential(identity:identity,certificates:certificates.isEmpty ? nil : certificates,persistence:.forSession))
        } else if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust {
            #if RECEPTION_TESTING
            if let anchor=testAnchor, let trust=challenge.protectionSpace.serverTrust {
                guard SecTrustSetAnchorCertificates(trust,[anchor] as CFArray)==errSecSuccess,
                      SecTrustSetAnchorCertificatesOnly(trust,true)==errSecSuccess,
                      SecTrustEvaluateWithError(trust,nil) else { completion(.cancelAuthenticationChallenge,nil);return }
                completion(.useCredential,URLCredential(trust:trust));return
            }
            #endif
            completion(.performDefaultHandling,nil)
        } else { completion(.cancelAuthenticationChallenge,nil) }
    }
    func urlSession(_ session:URLSession,didReceive challenge:URLAuthenticationChallenge,
                    completionHandler:@escaping(URLSession.AuthChallengeDisposition,URLCredential?)->Void) { self.challenge(challenge,completionHandler) }
    func urlSession(_ session:URLSession,task:URLSessionTask,didReceive challenge:URLAuthenticationChallenge,
                    completionHandler:@escaping(URLSession.AuthChallengeDisposition,URLCredential?)->Void) { self.challenge(challenge,completionHandler) }
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,
                    newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void) { completionHandler(nil) }
    func urlSession(_ session:URLSession,dataTask:URLSessionDataTask,didReceive response:URLResponse,
                    completionHandler:@escaping(URLSession.ResponseDisposition)->Void) {
        guard let http=response as? HTTPURLResponse, http.url?.host==host else {
            reject(dataTask,"reception_transport_uncertain");completionHandler(.cancel);return
        }
        guard (http.value(forHTTPHeaderField:"Content-Encoding") ?? "identity").lowercased()=="identity" else {
            reject(dataTask,"reception_response_encoding");completionHandler(.cancel);return
        }
        guard response.expectedContentLength<=Int64(maxBody) else {
            reject(dataTask,"reception_response_size");completionHandler(.cancel);return
        }
        lock.lock();status=http.statusCode
        if let value=http.value(forHTTPHeaderField:"Retry-After"), digits(value,1,7), let seconds=Int(value) { retry=min(seconds,86400) }
        lock.unlock();completionHandler(.allow)
    }
    func urlSession(_ session:URLSession,dataTask:URLSessionDataTask,didReceive data:Data) {
        lock.lock()
        if bytes.count+data.count>maxBody { failure="reception_response_size";lock.unlock();dataTask.cancel();return }
        bytes.append(data);lock.unlock()
    }
    func urlSession(_ session:URLSession,task:URLSessionTask,didCompleteWithError error:Error?) {
        lock.lock();if error != nil && failure == nil { failure="reception_transport_uncertain" };lock.unlock();done.signal()
    }
}
let config=URLSessionConfiguration.ephemeral
config.httpCookieStorage=nil;config.urlCredentialStorage=nil;config.urlCache=nil
config.connectionProxyDictionary=[kCFNetworkProxiesHTTPEnable as String:0,kCFNetworkProxiesHTTPSEnable as String:0,
    kCFNetworkProxiesSOCKSEnable as String:0,kCFNetworkProxiesProxyAutoConfigEnable as String:0,kCFNetworkProxiesProxyAutoDiscoveryEnable as String:0]
config.tlsMinimumSupportedProtocolVersion = .TLSv12
config.timeoutIntervalForRequest=10;config.timeoutIntervalForResource=30
config.httpMaximumConnectionsPerHost=1;config.httpShouldUsePipelining=false;config.waitsForConnectivity=false
let receiver=Receiver(identity,chain,host,testAnchor,presentClient)
let queue=OperationQueue();queue.maxConcurrentOperationCount=1
let session=URLSession(configuration:config,delegate:receiver,delegateQueue:queue)
var request=URLRequest(url:url,cachePolicy:.reloadIgnoringLocalCacheData,timeoutInterval:10)
request.httpMethod=method;request.httpBody=requestBody
#if RECEPTION_TESTING
request.setValue(testOriginalEndpoint,forHTTPHeaderField:"X-Escritura-Test-Original-URL")
#endif
request.setValue(provider=="nfse_adn" ? "application/json" : "application/soap+xml",forHTTPHeaderField:"Accept")
request.setValue("identity",forHTTPHeaderField:"Accept-Encoding")
request.setValue("EscrituraIntegrada/Reception",forHTTPHeaderField:"User-Agent")
if let contentType=contentType { request.setValue(contentType,forHTTPHeaderField:"Content-Type") }
session.dataTask(with:request).resume()
guard receiver.done.wait(timeout: .now()+35) == .success else { session.invalidateAndCancel();fail("reception_transport_uncertain") }
session.invalidateAndCancel()
receiver.lock.lock()
let responseData=receiver.bytes;let responseStatus=receiver.status;let retry=receiver.retry;let failure=receiver.failure
receiver.lock.unlock()
if let failure=failure { fail(failure) }
guard (100...599).contains(responseStatus) else { fail("reception_transport_uncertain") }
output(metadata.merging(["http_status":responseStatus,"retry_after":retry,"body_base64":responseData.base64EncodedString()]) { _,new in new })
