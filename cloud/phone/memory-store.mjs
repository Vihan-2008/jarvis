// An in-memory stand-in for the relay's Store (PostgREST + Storage), for the tests. Same methods, same meaning.
export class MemoryStore {
  constructor(clock = () => Date.now()) {
    this.now = clock;
    this.state = new Map(); this.seen = new Set(); this.inbox = new Map(); this.offlog = []; this.transcript = [];
    this.phonesRows = new Map(); this.files = new Map(); this.blobs = new Map(); this.seq = 0; this.tseq = 0;
  }
  async get(key) { return this.state.has(key) ? structuredClone(this.state.get(key).value) : null; }
  async put(key, value) { this.state.set(key, { value: structuredClone(value), at: this.now() }); }
  async drop(key) { this.state.delete(key); }
  async dropAll() { this.state.clear(); }
  async like(prefix) { return [...this.state].filter(([k]) => k.startsWith(prefix)).map(([key, v]) => ({ key, value: structuredClone(v.value) })); }
  async firstTime(id) { if (this.seen.has(id)) return false; this.seen.add(id); return true; }
  async inboxAdd(id, body) { if (this.inbox.has(id)) throw Error('duplicate'); this.inbox.set(id, { id, body, status: 'new', at: this.now(), claimed_at: null }); }
  async claim(id, from, to) { const r = this.inbox.get(id); if (!r || r.status !== from) return false; r.status = to; r.claimed_at = this.now(); return true; }
  async setInbox(id, fields) { const r = this.inbox.get(id); if (r) Object.assign(r, fields); }
  async stale(before) { return [...this.inbox.values()].filter(r => r.status === 'new' && r.at < before).slice(0, 5).map(({ id, body }) => ({ id, body })); }
  async take(most) {
    const rows = [...this.inbox.values()].filter(r => r.status === 'new' || r.status === 'deferred' || (r.status === 'taken' && r.claimed_at < this.now() - 600000))
      .sort((a, b) => a.at - b.at).slice(0, most);
    for (const r of rows) { r.status = 'taken'; r.claimed_at = this.now(); }
    return rows.map(r => ({ ...r }));
  }
  async forget(table, ids) {
    if (table === 'ph_inbox') ids.forEach(id => this.inbox.delete(id));
    if (table === 'ph_offlog') this.offlog = this.offlog.filter(r => !ids.includes(r.id));
    if (table === 'ph_files') ids.forEach(id => this.files.delete(id));
  }
  async clear(table) { if (table === 'ph_inbox') this.inbox.clear(); if (table === 'ph_offlog') this.offlog = []; if (table === 'ph_transcript') this.transcript = []; }
  async bump(counter, period, most) {
    const v = this.state.get(counter)?.value;
    const used = v && v.period === period ? v.n : 0;
    if (used >= most) return -1;
    this.state.set(counter, { value: { period, n: used + 1 }, at: this.now() });
    return used + 1;
  }
  async add(table, body) { if (table === 'ph_offlog') this.offlog.push({ id: ++this.seq, at: this.now(), body }); }
  async list(table, most = 20) { return table === 'ph_offlog' ? this.offlog.slice(0, most) : []; }
  async count(table) { return table === 'ph_offlog' ? this.offlog.length : 0; }
  async tidy() { this.tidied = (this.tidied || 0) + 1; }
  async say(row) { const id = ++this.tseq; this.transcript.push({ id, at: this.now(), ...row }); return id; }
  async after(id, most = 50) { return this.transcript.filter(r => r.id > id).slice(0, most).map(r => ({ ...r })); }
  async latest() { return this.transcript.length ? this.transcript[this.transcript.length - 1].id : 0; }
  async mark(msgId, status) { for (const r of this.transcript) if (r.msg_id === msgId) r.status = status; }
  async trim(keep = 50) { this.transcript = this.transcript.slice(-keep); }
  async phones() { return [...this.phonesRows.values()].map(p => ({ ...p })); }
  async phone(id) { const p = this.phonesRows.get(id); return p ? { ...p } : null; }
  async phoneAdd(row) { this.phonesRows.set(row.id, { revoked: false, push: null, added: this.now(), last_seen: null, ...row }); }
  async phoneSet(id, fields) { const p = this.phonesRows.get(id); if (p) Object.assign(p, fields); }
  async fileAdd(row) { this.files.set(row.id, { ...row, at: this.now() }); }
  async file(id) { const f = this.files.get(id); return f ? { ...f } : null; }
  async filesTotal() { return [...this.files.values()].reduce((n, f) => n + f.size, 0); }
  async filesBefore(before) { return [...this.files.values()].filter(f => f.at < before).map(f => ({ id: f.id })); }
  async blobPut(id, bytes) { this.blobs.set(id, bytes); }
  async blobGet(id) { return this.blobs.get(id) || null; }
  async blobDrop(ids) { ids.forEach(id => this.blobs.delete(id)); }
}
