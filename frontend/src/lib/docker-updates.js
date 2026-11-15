import {uid} from './format.js';
// State survives uncertain transport failures while this view is cached.
export function createDockerUpdates(model, api, key = () => uid().replaceAll('-', '')) {
  let generation = 0, alive = true;
  const valid = g => alive && g === generation;
  async function perform(fn, apply) {
    if (model.busy || !alive) return;
    const g = generation;
    model.busy = true; model.error = '';
    try { const result = await fn(); if (valid(g)) apply(result); }
    catch (e) { if (valid(g)) model.error = e.message; }
    finally { if (valid(g)) model.busy = false; }
  }
  return {
    status: () => perform(() => api('/docker-updates'), result => { model.status = result; }),
    check: () => perform(() => api('/docker-updates/check', {method:'POST', body:{channel:model.channel}}), result => {
      model.plan = result; model.intent = {plan_id:result.id, idempotency_key:key()};
    }),
    prepare: () => {
      if (!model.intent) return;
      const intent = {...model.intent};
      return perform(() => api('/docker-updates/prepare', {method:'POST', body:intent}), result => {
        model.job = result;
        // Keep intent for retries; executor deduplicates the persisted snapshot.
      });
    },
    channel: channel => { if (model.busy) return; generation++; model.channel=channel; model.plan=null; model.intent=null; model.error=''; },
    pause: () => { alive=false; generation++; model.busy=false; },
    resume: () => { alive=true; },
  };
}
