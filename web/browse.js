export function scopeKey(source, conference = 'all', review = 'accepted') {
  return source === 'conferences' && conference !== 'all' ? `conferences/${conference}` : source === 'openreview' ? `openreview/${review}` : source;
}

// Include zero-record days between the oldest collected date and today.
export function dateChoices(counts, today, selected = '') {
  const dates = Object.keys(counts).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d) && d <= today);
  if (/^\d{4}-\d{2}-\d{2}$/.test(selected) && selected <= today) dates.push(selected);
  const oldest = dates.sort()[0] || today;
  const result = [];
  for (let day = new Date(today + 'T00:00:00Z'); day.toISOString().slice(0, 10) >= oldest; day.setUTCDate(day.getUTCDate() - 1)) {
    result.push(day.toISOString().slice(0, 10));
  }
  return result;
}

export function selectShards(catalog, {source = 'all', conference = 'all', date = '', year = '', datedOnly = false} = {}) {
  return (catalog.paper_shards || []).filter(s =>
    (!datedOnly || s.dated_count !== 0) &&
    (source === 'all' || s.sources.includes(source)) &&
    (source !== 'conferences' || conference === 'all' || s.conferences.includes(conference)) &&
    (!date || !s.dates || s.dates.includes(date)) &&
    (!year || !s.years || s.years.includes(year)));
}

// Content-addressed files are immutable: share in-flight requests and browser cache.
export function createShardLoader(fetcher = fetch) {
  const cache = new Map();
  const get = shard => {
    if (!/^papers\/part-[a-f0-9]+\.json$/.test(shard.file)) return Promise.reject(new Error('论文分片路径不正确'));
    if (!cache.has(shard.file)) cache.set(shard.file, fetcher('./data/' + shard.file, {cache:'force-cache'}).then(async response => {
      if (!response.ok) {const error=new Error('论文加载失败，请刷新论文库重试');error.status=response.status;throw error;}
      const rows = await response.json();
      if (!Array.isArray(rows)) throw new Error('论文分片格式不正确');
      return rows;
    }).catch(error => { cache.delete(shard.file); throw error; }));
    return cache.get(shard.file);
  };
  return async (shards, {active = () => true, progress = () => {}, concurrency = 4} = {}) => {
    let cursor = 0, completed = 0;
    const loaded = [];
    await Promise.all(Array.from({length:Math.min(concurrency,shards.length)}, async () => {
      while (cursor < shards.length && active()) {
        const rows = await get(shards[cursor++]);
        if (!active()) return;
        loaded.push(...rows); progress(loaded, ++completed, shards.length);
      }
    }));
    return loaded;
  };
}
