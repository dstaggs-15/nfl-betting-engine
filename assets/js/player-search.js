import {node} from './api.js';

export function playerSearch(input, list, players, onSelect) {
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  let matches = [], active = -1;
  const close = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };
  const choose = player => {
    input.value = player.player_name;
    close();
    onSelect(player);
    input.focus();
  };
  const highlight = () => {
    [...list.children].forEach((el, i) => {
      el.classList.toggle('active', i === active);
      el.setAttribute('aria-selected', String(i === active));
    });
    if (active >= 0) {
      input.setAttribute('aria-activedescendant', list.children[active].id);
      list.children[active].scrollIntoView({block: 'nearest'});
    }
  };
  const show = () => {
    const query = input.value.trim().toLowerCase();
    list.replaceChildren();
    active = -1;
    input.removeAttribute('aria-activedescendant');
    if (!query) { close(); return; }
    matches = players.filter(p => `${p.player_name} ${p.team || ''}`.toLowerCase().includes(query))
      .sort((a,b) => (b.line_count || 0) - (a.line_count || 0) || a.player_name.localeCompare(b.player_name))
      .slice(0, 8);
    if (!matches.length) { close(); return; }
    for (const [i, player] of matches.entries()) {
      const option = node('div', '', 'player-option');
      option.id = `${list.id}-${i}`;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      option.append(node('strong', player.player_name), node('small',
        `${player.team || ''}${player.line_count == null ? '' : player.line_count ? ` · ${player.line_count} lines` : ' · No published lines'}`));
      option.addEventListener('pointerdown', event => { event.preventDefault(); choose(player); });
      list.append(option);
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', show);
  input.addEventListener('blur', close);
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(); return; }
    if (list.hidden || !matches.length) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
      highlight();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(matches[active >= 0 ? active : 0]);
    }
  });
}
