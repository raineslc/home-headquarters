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
// Show only the repeat controls that apply to the chosen frequency and end.
document.querySelectorAll('[data-repeat]').forEach(group => {
  // Assistant review cards prefix field names with the suggestion ID, so match on the suffix.
  const value = name => (group.querySelector(`[name="${name}"], [name$="-${name}"]`) || {}).value;
  const update = () => {
    const repeat = value('repeat');
    const ends = value('ends');
    const mode = group.querySelector('[name="repeat_mode"]:checked');
    const afterDone = mode && mode.value === 'after';
    group.querySelectorAll('[data-repeat-field]').forEach(row => {
      const name = row.dataset.repeatField;
      row.hidden = name !== 'repeat' && (!repeat || (name === 'weekdays' && (repeat !== 'WEEKLY' || afterDone)) ||
        (name === 'monthly_by' && (repeat !== 'MONTHLY' || afterDone)) || (name === 'until' && ends !== 'until') || (name === 'count' && ends !== 'count'));
    });
  };
  group.addEventListener('change', update);
  update();
});
// Multi-date add: select a weekday column and keep the chosen-date count current.
document.querySelectorAll('[data-bulk-grid]').forEach(grid => {
  const form = grid.closest('form');
  const count = form.querySelector('[data-bulk-count]');
  const boxes = () => Array.from(grid.querySelectorAll('input[name="dates"]'));
  const update = () => {
    const total = boxes().filter(box => box.checked).length;
    if (count) count.textContent = `${total} date${total === 1 ? '' : 's'} chosen`;
  };
  grid.querySelectorAll('.weekday-toggle').forEach(button => {
    button.addEventListener('click', () => {
      const column = boxes().filter(box => box.dataset.weekday === button.dataset.weekday);
      const select = !column.every(box => box.checked);
      column.forEach(box => { box.checked = select; });
      update();
    });
  });
  grid.addEventListener('change', update);
});
// Installable phone app: register the service worker and offer Install where the browser allows it.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}); });
}
(() => {
  const standalone = window.matchMedia('(display-mode: standalone)').matches;
  document.querySelectorAll('[data-installed]').forEach(note => { note.hidden = !standalone; });
  let deferred = null;
  const remembered = () => { try { return localStorage.getItem('hhq-install-dismissed') === '1'; } catch (error) { return false; } };
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferred = event;
    document.querySelectorAll('[data-install-ready]').forEach(block => { block.hidden = false; });
    const banner = document.querySelector('[data-install-banner]');
    if (banner && !remembered()) banner.hidden = false;
  });
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-install]') && deferred) {
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      document.querySelectorAll('[data-install-banner], [data-install-ready]').forEach(item => { item.hidden = true; });
    } else if (event.target.closest('[data-install-dismiss]')) {
      try { localStorage.setItem('hhq-install-dismissed', '1'); } catch (error) { /* private mode */ }
      document.querySelector('[data-install-banner]').hidden = true;
    }
  });
  window.addEventListener('appinstalled', () => {
    document.querySelectorAll('[data-install-banner], [data-install-ready]').forEach(item => { item.hidden = true; });
  });
})();
// Assistant review: keep the Add selected button's count in step with the ticked suggestions.
document.querySelectorAll('.proposal-review').forEach(form => {
  const button = form.querySelector('[data-add-selected]');
  if (!button) return;
  const update = () => {
    const count = form.querySelectorAll('[data-proposal-pick]:checked').length;
    button.textContent = count ? `Add ${count} selected` : 'Add selected';
    button.disabled = count === 0;
  };
  form.addEventListener('change', event => { if (event.target.matches('[data-proposal-pick]')) update(); });
  update();
});
// Voice input for the assistant (AI-09): Chrome's built-in speech recognition fills the text box.
// Nothing is sent to the assistant until the parent presses the usual button. Hidden where unsupported.
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const problems = {
    'not-allowed': 'Microphone access is blocked. Allow it for this site in your browser settings, or type instead.',
    'service-not-allowed': 'Voice input is turned off in this browser. You can type instead.',
    'no-speech': 'Didn’t catch that. Tap Speak and try again.',
    'audio-capture': 'No microphone was found.',
    'network': 'Voice input needs an internet connection.',
  };
  document.querySelectorAll('[data-dictate-for]').forEach(box => {
    const field = document.getElementById(box.dataset.dictateFor);
    if (!Recognition || !field || field.disabled) return;
    box.hidden = false;
    const button = box.querySelector('button');
    const label = box.querySelector('[data-mic-label]');
    const status = box.querySelector('.mic-status');
    const limit = Number(field.getAttribute('maxlength')) || 3000;
    let recognition = null;
    const finish = () => {
      recognition = null;
      box.classList.remove('listening');
      button.setAttribute('aria-pressed', 'false');
      label.textContent = 'Speak';
    };
    button.addEventListener('click', () => {
      if (recognition) { recognition.stop(); return; }
      const before = field.value.trim();
      let spoken = '';
      let failed = false;
      recognition = new Recognition();
      recognition.lang = navigator.language || 'en-US';
      recognition.interimResults = true;
      recognition.continuous = true;
      recognition.onresult = event => {
        let pending = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) spoken += result[0].transcript + ' '; else pending += result[0].transcript;
        }
        field.value = [before, (spoken + pending).trim()].filter(Boolean).join(' ').slice(0, limit);
      };
      recognition.onerror = event => {
        failed = true;
        status.textContent = problems[event.error] || (event.error === 'aborted' ? '' : 'Voice input stopped. You can type instead.');
      };
      recognition.onend = () => {
        finish();
        if (!failed) status.textContent = spoken.trim() ? 'Done. Check the text, then continue.' : '';
        field.focus();
      };
      try {
        recognition.start();
      } catch (error) {
        finish();
        status.textContent = 'Voice input could not start. You can type instead.';
        return;
      }
      box.classList.add('listening');
      button.setAttribute('aria-pressed', 'true');
      label.textContent = 'Stop';
      status.textContent = 'Listening… speak, then tap Stop.';
    });
    if (field.form) field.form.addEventListener('submit', () => { if (recognition) recognition.stop(); });
  });
})();

// Phone reminders (Settings): subscribe this device to Web Push and send a test.
(() => {
  const card = document.querySelector('[data-push-key]');
  if (!card || !card.dataset.pushKey) return;
  const status = card.querySelector('[data-push-status]');
  const buttons = {on: card.querySelector('[data-push-on]'), test: card.querySelector('[data-push-test]'), off: card.querySelector('[data-push-off]')};
  const token = card.querySelector('input[name=csrfmiddlewaretoken]').value;
  const say = text => { status.textContent = text; };
  const show = subscribed => { buttons.on.hidden = subscribed; buttons.test.hidden = buttons.off.hidden = !subscribed; };
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    say('This browser can’t receive reminders. On Android, use Chrome or the installed app.');
    return;
  }
  const post = (url, body) => fetch(url, {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': token}, body: JSON.stringify(body)})
    .then(response => response.json().catch(() => ({})).then(data => ({ok: response.ok, data})));
  const key = () => {
    const text = card.dataset.pushKey.replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(text + '='.repeat((4 - text.length % 4) % 4));
    return Uint8Array.from(raw, character => character.charCodeAt(0));
  };
  // The service worker receives reminders; give up politely if this browser can't start it.
  const ready = Promise.race([navigator.serviceWorker.ready,
    new Promise((resolve, reject) => setTimeout(() => reject(new Error('timeout')), 8000))]);
  const current = () => ready.then(registration => registration.pushManager.getSubscription().then(sub => ({registration, sub})));
  if (Notification.permission === 'denied') {
    say('Notifications are blocked for this site. Allow them in Chrome’s site settings, then reload.');
    return;
  }
  current().then(({sub}) => {
    if (sub) {
      // Re-save in case the server lost it (for example after a restore of another device).
      post('/push/subscribe/', sub.toJSON()).then(({ok}) => say(ok ? 'Reminders are on for this device.' : 'Reminders are on here, but the server didn’t confirm. Try turning them off and on.'));
      show(true);
    } else {
      say('Reminders are off for this device.');
      show(false);
    }
  }).catch(() => say('This browser couldn’t start the app’s background helper, so reminders can’t be turned on here. Reload, or use Chrome on your phone.'));
  buttons.on.addEventListener('click', async () => {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') { say('Notifications weren’t allowed, so reminders stay off.'); return; }
    say('Turning on…');
    try {
      const {registration} = await current();
      const sub = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key()});
      const {ok, data} = await post('/push/subscribe/', sub.toJSON());
      if (!ok) { await sub.unsubscribe(); say(data.error || 'The server couldn’t turn on reminders.'); return; }
      say('Reminders are on for this device. Send a test to check.');
      show(true);
    } catch (error) {
      say('This device couldn’t turn on reminders (' + error.name + ').');
    }
  });
  buttons.test.addEventListener('click', async () => {
    const {sub} = await current();
    if (!sub) { show(false); return; }
    const {ok, data} = await post('/push/test/', {endpoint: sub.endpoint});
    say(ok ? 'Test sent. It should appear within a few seconds.' : (data.error || 'The test couldn’t be sent.'));
  });
  buttons.off.addEventListener('click', async () => {
    const {sub} = await current();
    if (sub) { await post('/push/unsubscribe/', {endpoint: sub.endpoint}); await sub.unsubscribe(); }
    say('Reminders are off for this device.');
    show(false);
  });
})();

// Snap a flyer (AI-10): shrink the photo on the phone before upload; it is never stored.
document.querySelectorAll('input[data-flyer]').forEach(input => {
  const status = input.closest('.flyer').querySelector('[data-flyer-status]');
  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) { status.textContent = ''; return; }
    status.textContent = 'Getting the photo ready…';
    try {
      const bitmap = await createImageBitmap(file, {imageOrientation: 'from-image'});
      const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85));
      if (blob && (blob.size < file.size || !/^image\/(jpeg|png|webp)$/.test(file.type))) {
        const transfer = new DataTransfer();
        transfer.items.add(new File([blob], 'flyer.jpg', {type: 'image/jpeg'}));
        input.files = transfer.files;
      }
    } catch (error) { /* send the original; the server checks it */ }
    status.textContent = 'Photo added. Add a note if you like, then tap Prepare suggestions.';
  });
});
