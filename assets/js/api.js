export const $ = id => document.getElementById(id);
export function node(tag, text = '', className = '') { const el = document.createElement(tag); el.textContent = text; if(className) el.className=className; return el; }
export const pct = value => value == null ? '—' : `${(value*100).toFixed(1)}%`;
export const money = value => value == null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(value);
export const time = value => value ? new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(value)) : 'Not available';
export async function data(name) { const response=await fetch(`site/data/${name}.json`,{cache:'no-store'}); if(!response.ok) throw new Error(`Could not load ${name} (${response.status})`); return response.json(); }
export function cell(row, text, sub='', className='') { const td=node('td','',className); td.append(node('strong',text)); if(sub) td.append(node('small',sub)); row.append(td); return td; }
export function theme(){ try { if(localStorage.getItem('theme')==='light') document.body.classList.add('light'); } catch {} $('theme')?.addEventListener('click',()=>{document.body.classList.toggle('light');try{localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}catch{}}); }
export function showError(error){$('error').hidden=false;$('error').textContent=error.message;}
export function empty(container,text){container.append(node('p',text,'empty'));}
export function outcome(line) {
  const yes = line.direction === 'over';
  if (line.market === 'first_touchdown') return yes ? 'Scores first touchdown' : 'Does not score first touchdown';
  if (line.market === 'anytime_touchdown') return yes ? 'Scores a touchdown' : 'Does not score a touchdown';
  return line.display_line;
}
