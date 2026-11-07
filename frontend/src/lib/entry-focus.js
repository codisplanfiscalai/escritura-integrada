// Mantém erros e digitação na janela corrente; foco retorna ao campo relacionado.
export function focusError(id,message){
 const form=document.getElementById(id);if(!form)return;
 const bad=form.querySelector(':invalid');if(bad){bad.focus();return;}
 const words=/data|escritura|exercício|competência/i.test(message)?['escrituração','data']: /conta|partida|balanceado/i.test(message)?['conta']: /histórico/i.test(message)?['histórico']: /documento|identidade|chave/i.test(message)?['número','documento']: /valor|total|decimal/i.test(message)?['total','valor']:[];
 for(const label of form.querySelectorAll('label')){if(words.some(w=>label.textContent.toLocaleLowerCase().includes(w))){label.querySelector('input,select,textarea')?.focus();return;}}
 form.querySelector('input,select,textarea')?.focus();
}
export function firstField(id){document.getElementById(id)?.querySelector('input,select,textarea')?.focus();}
