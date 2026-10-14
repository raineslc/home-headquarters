document.addEventListener('change', (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  const form = input.closest('.lunch-form');
  if (form && input.matches('[data-all-month]')) {
    form.querySelectorAll('input[name="dates"]').forEach(day => { day.checked = input.checked; });
  } else if (form && input.name === 'dates') {
    const all = form.querySelector('[data-all-month]');
    const days = Array.from(form.querySelectorAll('input[name="dates"]'));
    all.checked = days.every(day => day.checked);
    all.indeterminate = !all.checked && days.some(day => day.checked);
  }
  if (input.name === 'activity-all_day') {
    input.closest('form').querySelectorAll('input[type="time"]').forEach(time => { time.disabled = input.checked; });
  }
});
document.querySelectorAll('.quick-panel').forEach(panel => {
  panel.addEventListener('toggle', () => {
    if (panel.open) panel.querySelector('input[name$="-title"]').focus();
  });
});
document.querySelectorAll('[data-ai-request]').forEach(form => {
  form.addEventListener('submit', () => {
    const progress = form.querySelector('.ai-progress');
    if (progress) progress.hidden = false;
    form.querySelectorAll('button[type="submit"]').forEach(button => { button.disabled = true; });
  });
});
