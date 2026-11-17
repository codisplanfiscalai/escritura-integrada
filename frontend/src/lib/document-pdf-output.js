// Own the original bytes independently of PDF.js, which may transfer its buffer.
export function createPdfOutput({urlApi=URL,doc=globalThis.document,nav=globalThis.navigator}={}) {
 let source='',frame=null,timer=null,finish=null,trigger=null;
 function cancelPrint(){
  clearTimeout(timer);timer=null;
  if(frame){frame.onload=null;frame.remove();frame=null;}
  const done=finish;finish=null;done?.();
  if(trigger?.isConnected)trigger.focus();trigger=null;
 }
 function dispose(){cancelPrint();if(source)urlApi.revokeObjectURL(source);source='';}
 function set(data){dispose();source=urlApi.createObjectURL(new Blob([data],{type:'application/pdf'}));return source;}
 function print(){
  cancelPrint();
  if(!source)return Promise.reject(new Error('Aguarde o carregamento do PDF.'));
  if(nav?.pdfViewerEnabled===false)return Promise.reject(new Error('Este navegador não oferece impressão de PDF incorporado. Use Baixar PDF e imprima no seu leitor de PDF.'));
  return new Promise((resolve,reject)=>{
   finish=resolve;trigger=doc.activeElement;const target=doc.createElement('iframe');frame=target;
   target.title='Impressão do documento original';target.setAttribute('aria-hidden','true');target.tabIndex=-1;
   target.style.cssText='position:fixed;width:1px;height:1px;bottom:0;left:0;border:0;pointer-events:none;opacity:0';
   timer=setTimeout(()=>{if(frame!==target)return;finish=null;cancelPrint();reject(new Error('O leitor de impressão não respondeu. Use Baixar PDF e imprima no seu leitor.'));},15000);
   target.onload=()=>{
    if(frame!==target)return;
    clearTimeout(timer);timer=null;target.onload=null;
    try{target.contentWindow.addEventListener('afterprint',()=>{if(frame===target)cancelPrint();},{once:true});target.contentWindow.focus();target.contentWindow.print();finish=null;resolve();}
    catch{finish=null;cancelPrint();reject(new Error('Não foi possível abrir a impressão. Use Baixar PDF e imprima no seu leitor.'));}
   };
   target.src=source;doc.body.appendChild(target);
  });
 }
 return {set,print,dispose};
}
