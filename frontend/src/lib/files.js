// Arquivos não substituem a área de trabalho, inclusive em respostas de erro.
export function fileName(disposition = '', fallback = 'arquivo') {
  const utf = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
  let name = utf?.[1] || plain?.[1] || plain?.[2] || fallback;
  if (utf) { try { name = decodeURIComponent(name); } catch { name = fallback; } }
  return name.replace(/\\/g, '/').split('/').pop().replace(/[\u0000-\u001f<>:"|?*]/g, '_').trim() || fallback;
}

export async function readFileResponse(response) {
  const type = response.headers.get('content-type') || '';
  const attachment = /filename\*?=/i.test(response.headers.get('content-disposition') || '');
  if (!response.ok || (!attachment && (type.includes('application/json') || type.includes('text/html')))) {
    let data; try { data = await response.json(); } catch { data = {}; }
    const message = typeof data.detail === 'string' ? data.detail : 'Não foi possível gerar o arquivo. Confira a sessão, o acesso e os filtros e tente novamente.';
    const error = new Error(message); error.status = response.status; throw error;
  }
  const blob = await response.blob();
  if (!blob.size) throw new Error('O arquivo gerado está vazio. Confira os filtros e tente novamente.');
  return { blob, name: fileName(response.headers.get('content-disposition')) };
}

export function installFileLinks(notify) {
  const pending = new Set();
  const handler = async event => {
    const link = event.target.closest?.('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) return;
    // A impressão abre uma página própria; o desktop encaminha PDFs ao leitor nativo.
    if (link.target === '_blank') return;
    event.preventDefault();
    if (pending.has(url.href)) return;
    pending.add(url.href); link.setAttribute('aria-busy', 'true');
    notify('Preparando arquivo…', 'info');
    try {
      const response = await fetch(url.href, { credentials: 'same-origin' });
      const { blob, name } = await readFileResponse(response);
      const objectUrl = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = objectUrl; download.download = name;
      document.body.append(download); download.click(); download.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
      notify('Arquivo preparado. Confira o salvamento na janela de downloads.', 'success');
    } catch (error) { notify(error.message || 'Falha de comunicação ao preparar o arquivo. Tente novamente.', 'error'); }
    finally { pending.delete(url.href); link.removeAttribute('aria-busy'); }
  };
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}
