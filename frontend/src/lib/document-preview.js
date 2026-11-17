export const auxiliaryLabel = model => ({55:'DANFE',65:'DANFC-e',57:'DACTE'})[model] || 'Documento auxiliar';

// Abort is an optimization; the generation check also rejects late responses
// from transports that have already completed or cannot be cancelled.
export function createPdfRequest(fetcher = globalThis.fetch) {
  let generation = 0, controller;
  const cancel = () => { generation++; controller?.abort(); controller = null; };
  async function load(url) {
    cancel();
    const current = generation;
    controller = new AbortController();
    try {
      const response = await fetcher(url, {signal:controller.signal, credentials:'same-origin', cache:'no-store'});
      if (current !== generation) return null;
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || 'Não foi possível abrir o documento original. Tente novamente.');
      }
      if (!response.headers.get('content-type')?.startsWith('application/pdf')) throw new Error('A resposta não contém um PDF válido.');
      const data = new Uint8Array(await response.arrayBuffer());
      return current === generation ? data : null;
    } catch (error) {
      if (current !== generation || error.name === 'AbortError') return null;
      throw error;
    }
  }
  return {load, cancel};
}
