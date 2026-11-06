/* WOWBOX status page - live health of the box, in plain language */

const STATUS_POLL_MS = 5000;
const LOG_POLL_MS = 4000;
const MAX_LOG_LINES = 400;

let lastLogId = 0;
let allLogs = [];
let logFilter = 'all';
let lastData = null;

const $ = (id) => document.getElementById(id);

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
}

function parseUTC(iso) {
    if (!iso) return null;
    return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
}

function ago(seconds) {
    if (seconds == null) return 'never';
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return `${Math.floor(seconds / 86400)} d ago`;
}

function duration(seconds) {
    if (seconds == null) return '-';
    const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    return `${m}m`;
}

function toast(msg) {
    const t = $('st-toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2600);
}

// ─── Health evaluation ────────────────────────────────────────────────────────
// Each check: {key, label, state: ok|warn|bad|unknown, detail, hint}

function evaluate(data) {
    const s = data.status || {};
    const net = s.network || {};
    const pr = s.printer || {};
    const sp = s.speaker || {};
    const sys = s.system || {};
    const online = data.online;
    const checks = [];
    const offlineDetail = 'Unknown while the box is offline';

    // Box
    if (!data.last_seen) {
        checks.push({ key: 'box', label: 'Box is on and connected to the app', state: 'bad',
            detail: 'The box has never connected to the server.',
            hint: 'Plug the box in, switch the phone hotspot ON and wait 1-2 minutes. If it still does not appear, the box needs its Wi-Fi set up.' });
    } else if (!online) {
        checks.push({ key: 'box', label: 'Box is on and connected to the app', state: 'bad',
            detail: `Not responding - last seen ${ago(data.seconds_since_seen)}.`,
            hint: 'Is the box plugged in and switched on? Is the phone hotspot ON (with mobile data)? After power-up it takes 1-2 minutes to appear.' });
    } else {
        checks.push({ key: 'box', label: 'Box is on and connected to the app', state: 'ok',
            detail: `Online - last check-in ${ago(data.seconds_since_seen)}.` });
    }

    const live = online && data.last_seen;
    const unknown = (key, label) => ({ key, label, state: 'unknown', detail: offlineDetail });

    // Wi-Fi + internet
    if (!live) {
        checks.push(unknown('wifi', 'Box is on Wi-Fi'), unknown('internet', 'Internet works'));
    } else {
        if (!net.ssid) {
            checks.push({ key: 'wifi', label: 'Box is on Wi-Fi', state: 'warn',
                detail: 'The box reports no Wi-Fi name (it may be on a cable).',
                hint: 'If the box should use the hotspot, check the hotspot name and password.' });
        } else if (net.signal != null && net.signal < 30) {
            checks.push({ key: 'wifi', label: 'Box is on Wi-Fi', state: 'warn',
                detail: `Connected to "${net.ssid}" but the signal is weak (${net.signal}%).`,
                hint: 'Move the phone closer to the box.' });
        } else {
            checks.push({ key: 'wifi', label: 'Box is on Wi-Fi', state: 'ok',
                detail: `Connected to "${net.ssid}"${net.signal != null ? ` (signal ${net.signal}%)` : ''}.` });
        }
        checks.push(net.internet
            ? { key: 'internet', label: 'Internet works', state: 'ok', detail: 'The box can reach the internet.' }
            : { key: 'internet', label: 'Internet works', state: 'bad', detail: 'Connected to Wi-Fi but no internet.',
                hint: 'Check that the phone hotspot has mobile data / signal.' });
    }

    // Printer
    if (!live) {
        checks.push(unknown('printer', 'Printer is connected'));
    } else if (s.demo_mode) {
        checks.push({ key: 'printer', label: 'Printer is connected', state: 'warn',
            detail: 'Demo mode is ON - the printer is skipped on purpose.',
            hint: 'Triple-click the box button to switch demo mode off (blue flash = off).' });
    } else if (pr.adapter_up === false) {
        checks.push({ key: 'printer', label: 'Printer is connected', state: 'bad',
            detail: "The box's Bluetooth is switched off.",
            hint: 'Press "Restart box software". If it does not help, unplug and replug the box.' });
    } else if (pr.reachable === true) {
        if (pr.no_paper) {
            checks.push({ key: 'printer', label: 'Printer is connected', state: 'bad',
                detail: 'The printer is connected but out of paper.', hint: 'Load a new pack of ZINK paper.' });
        } else if (pr.cover_open) {
            checks.push({ key: 'printer', label: 'Printer is connected', state: 'bad',
                detail: 'The printer cover is open.', hint: 'Close the paper cover on the printer.' });
        } else if (pr.battery != null && pr.battery < 20) {
            checks.push({ key: 'printer', label: 'Printer is connected', state: 'warn',
                detail: `Connected, but the battery is low (${pr.battery}%).`, hint: 'Charge the printer.' });
        } else {
            checks.push({ key: 'printer', label: 'Printer is connected', state: 'ok',
                detail: `Connected${pr.battery != null ? ` - battery ${pr.battery}%` : ''}, paper OK (checked ${ago(pr.checked_ago_s)}).` });
        }
    } else if (pr.reachable === false) {
        checks.push({ key: 'printer', label: 'Printer is connected', state: 'bad',
            detail: pr.error || 'The printer cannot be reached.',
            hint: 'Switch the printer on, make sure it is charged and close to the box, then press "Check printer now".' });
    } else {
        checks.push({ key: 'printer', label: 'Printer is connected', state: 'unknown',
            detail: 'Not checked yet - the first check happens shortly after the box starts.' });
    }

    // Speaker
    if (!live) {
        checks.push(unknown('speaker', 'Speaker output is ready'));
    } else if (!sp.available) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'bad',
            detail: 'The box found no audio output.',
            hint: 'Check the audio cable is fully plugged into the box and the speaker, then press "Restart box software".' });
    } else if (sp.muted) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'warn',
            detail: `Audio output "${sp.sink || 'default'}" is muted.`, hint: 'Un-mute the box (or restart the box software).' });
    } else if (sp.volume === 0) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'warn',
            detail: `Audio output "${sp.sink || 'default'}" is connected but the volume is at 0% - the box will be silent.`,
            hint: 'Raise the box volume (SSH: wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.5). A volume control in this page is a good next step.' });
    } else if (data.speaker_confirm && data.speaker_confirm.ok === false) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'bad',
            detail: `You could not hear the last test sound (${ago(data.speaker_confirm.ago_s)}).`,
            hint: 'Check the speaker is switched ON, charged, the volume is up, and the audio cable is pushed in fully at both ends. Then press "Test speaker" again.' });
    } else if (data.speaker_confirm && data.speaker_confirm.ok === true) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'unknown',
            detail: `Sound heard OK ${ago(data.speaker_confirm.ago_s)} - audio output "${sp.sink || 'default'}" at ${sp.volume != null ? sp.volume + '%' : '?'}.` });
    } else if (sp.last_test_ok === false) {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'bad',
            detail: 'The last speaker test failed.', hint: 'Check the cable and that the speaker is switched on.' });
    } else {
        checks.push({ key: 'speaker', label: 'Speaker output is ready', state: 'unknown',
            detail: `Audio output "${sp.sink || 'default'}" at ${sp.volume != null ? sp.volume + '%' : '?'}. ` +
                (sp.last_test_ago_s != null ? `Last test ${ago(sp.last_test_ago_s)}.` : 'Press "Test speaker" and listen to confirm.') });
    }

    // System health (only warnings, never blocks)
    const sysWarnings = [];
    if (live) {
        if (sys.cpu_temp != null && sys.cpu_temp >= 75) sysWarnings.push(`The box is running hot (${sys.cpu_temp}\u00B0C) - make sure it has airflow.`);
        if (sys.disk_free_mb != null && sys.disk_free_mb < 300) sysWarnings.push(`The box is almost out of storage (${sys.disk_free_mb} MB free).`);
        if (sys.mem_free_mb != null && sys.mem_free_mb < 60) sysWarnings.push(`The box is low on memory (${sys.mem_free_mb} MB free).`);
        if (s.last_error && s.last_error.ago_s < 900) sysWarnings.push(`Recent problem (${ago(s.last_error.ago_s)}): ${s.last_error.message}`);
    }
    return { checks, sysWarnings };
}

// ─── Rendering ────────────────────────────────────────────────────────────────

const TICK = { ok: '\u2713', warn: '!', bad: '\u2715', unknown: '?' };

function renderHero(data, checks, sysWarnings) {
    const bad = checks.filter(c => c.state === 'bad');
    const warn = checks.filter(c => c.state === 'warn');
    const el = $('st-hero');
    let cls, icon, title, sub;
    if (!data.last_seen) {
        cls = 'bad'; icon = '\u2715'; title = 'The box has not connected yet';
        sub = 'Plug it in, turn the phone hotspot on and wait 1-2 minutes.';
    } else if (!data.online) {
        cls = 'bad'; icon = '\u2715'; title = 'The box is offline';
        sub = `Last seen ${ago(data.seconds_since_seen)}. The details below are from before it went offline.`;
    } else if (bad.length) {
        cls = 'bad'; icon = '!'; title = bad.length === 1 ? '1 thing needs fixing' : `${bad.length} things need fixing`;
        sub = bad[0].detail;
    } else if (warn.length || sysWarnings.length) {
        cls = 'warn'; icon = '!'; title = 'Working, with a heads-up';
        sub = (warn[0] && warn[0].detail) || sysWarnings[0];
    } else {
        cls = 'ok'; icon = '\u2665'; title = 'The box is ready';
        sub = 'Everything is connected - photos you send will arrive and print.';
    }
    el.className = `st-hero ${cls}`;
    $('st-hero-icon').textContent = icon;
    $('st-hero-title').textContent = title;
    $('st-hero-sub').textContent = sub;
}

function renderSteps(data) {
    const s = data.status || {};
    const order = ['downloading', 'waiting_for_button', 'printing', 'done'];
    const stage = data.online ? s.stage : 'offline';
    const idx = order.indexOf(stage);
    document.querySelectorAll('#st-steps li').forEach((li, i) => {
        li.classList.remove('done', 'active');
        if (idx >= 0) {
            if (i < idx) li.classList.add('done');
            else if (i === idx) li.classList.add('active');
        }
    });
    let text;
    if (!data.last_seen) text = 'Waiting for the box to connect for the first time.';
    else if (!data.online) text = 'The box is offline - nothing is happening.';
    else if (stage === 'error') text = `Last job failed: ${s.stage_detail || 'unknown error'}`;
    else text = s.stage_detail || 'Waiting for photos';
    if (data.online && s.demo_mode) text += ' (demo mode)';
    $('st-now').textContent = text;

    const q = data.queue || {};
    const bits = [];
    if (q.pending) bits.push(`${q.pending} waiting`);
    if (q.printing) bits.push(`${q.printing} in progress`);
    if (q.failed) bits.push(`${q.failed} failed`);
    if (q.completed) bits.push(`${q.completed} printed`);
    $('st-queue').textContent = bits.length ? `Queue: ${bits.join(' \u00B7 ')}` : 'Queue is empty.';
}

function renderTodo(checks, sysWarnings) {
    const items = [];
    checks.filter(c => c.state === 'bad' || c.state === 'warn').forEach(c => {
        items.push(`<li class="${c.state}"><b>${esc(c.label)}</b>${esc(c.detail)}${c.hint ? `<br><i>${esc(c.hint)}</i>` : ''}</li>`);
    });
    sysWarnings.forEach(w => items.push(`<li><b>Heads-up</b>${esc(w)}</li>`));
    $('st-todo').innerHTML = items.join('');
    $('st-todo-card').classList.toggle('st-hidden', items.length === 0);
}

function renderChecklist(checks) {
    $('st-checklist').innerHTML = checks.map(c => `
        <li><span class="st-tick ${c.state}">${TICK[c.state]}</span>
            <div>${esc(c.label)}<small>${esc(c.detail)}</small></div></li>`).join('');
}

function kv(k, v) { return `<div class="st-kv"><span>${esc(k)}</span><span>${esc(v)}</span></div>`; }
function pill(state, text) { return `<span class="st-pill ${state}">${esc(text)}</span>`; }

function renderCards(data, checks) {
    const s = data.status || {};
    const net = s.network || {}, pr = s.printer || {}, sp = s.speaker || {}, sys = s.system || {};
    const st = (key) => (checks.find(c => c.key === key) || {}).state || 'unknown';
    const word = { ok: 'OK', warn: 'Check', bad: 'Problem', unknown: 'Unknown' };
    const live = data.online;
    const yn = (v) => v == null ? '-' : v ? 'Yes' : 'No';

    const cards = [
        `<section class="st-card st-mini"><h3>\uD83D\uDCE6 Box ${pill(st('box'), live ? 'Online' : 'Offline')}</h3>
            ${kv('Last seen', data.last_seen ? ago(data.seconds_since_seen) : 'never')}
            ${kv('Running for', live ? duration(s.uptime_s) : '-')}
            ${kv('Software', s.version ? 'v' + s.version : '-')}
            ${kv('Demo mode', s.demo_mode ? 'ON' : 'off')}</section>`,

        `<section class="st-card st-mini"><h3>\uD83D\uDCF6 Network ${pill(st('internet') === 'ok' && st('wifi') !== 'bad' ? st('wifi') : (st('wifi') === 'bad' ? 'bad' : st('internet')), word[st('internet')])}</h3>
            ${kv('Wi-Fi', net.ssid || '-')}
            ${kv('Signal', net.signal != null ? net.signal + '%' : '-')}
            ${kv('Box address', net.ip || '-')}
            ${kv('Internet', live ? yn(net.internet) : '-')}
            ${kv('Server link', live ? (net.server_reachable === false ? 'Failing' : 'OK') : '-')}</section>`,

        `<section class="st-card st-mini"><h3>\uD83D\uDDA8 Printer ${pill(st('printer'), word[st('printer')])}</h3>
            ${kv('Bluetooth', pr.adapter_up == null ? '-' : pr.adapter_up ? 'On' : 'Off')}
            ${kv('Reachable', yn(pr.reachable))}
            ${kv('Battery', pr.battery != null ? pr.battery + '%' : '-')}
            ${kv('Paper', pr.no_paper == null ? '-' : pr.no_paper ? 'EMPTY' : 'OK')}
            ${kv('Cover', pr.cover_open == null ? '-' : pr.cover_open ? 'OPEN' : 'Closed')}
            ${kv('Last check', pr.checked_ago_s != null ? ago(pr.checked_ago_s) : 'never')}
            ${kv('Address', pr.mac || '-')}</section>`,

        `<section class="st-card st-mini"><h3>\uD83D\uDD0A Speaker ${pill(st('speaker'), word[st('speaker')])}</h3>
            ${kv('Output found', live ? yn(sp.available) : '-')}
            ${kv('Device', sp.sink || '-')}
            ${kv('Volume', sp.volume != null ? sp.volume + '%' : '-')}
            ${kv('Muted', sp.muted == null ? '-' : yn(sp.muted))}
            ${kv('Last test', sp.last_test_ago_s != null ? `${ago(sp.last_test_ago_s)} (${sp.last_test_ok ? 'sent' : 'failed'})` : 'never')}</section>`,

        `<section class="st-card st-mini"><h3>\uD83D\uDD27 Box health</h3>
            ${kv('Temperature', sys.cpu_temp != null ? sys.cpu_temp + '\u00B0C' : '-')}
            ${kv('Free memory', sys.mem_free_mb != null ? sys.mem_free_mb + ' MB' : '-')}
            ${kv('Free storage', sys.disk_free_mb != null ? sys.disk_free_mb + ' MB' : '-')}
            ${kv('Load', sys.load != null ? sys.load : '-')}</section>`,
    ];
    $('st-grid').innerHTML = cards.join('');
}

function render(data) {
    lastData = data;
    const { checks, sysWarnings } = evaluate(data);
    renderHero(data, checks, sysWarnings);
    renderSteps(data);
    renderTodo(checks, sysWarnings);
    renderChecklist(checks);
    renderCards(data, checks);
    $('st-updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
}

// ─── Log ──────────────────────────────────────────────────────────────────────

function levelGroup(level) {
    level = (level || 'info').toLowerCase();
    if (level === 'warning' || level === 'warn') return 'warn';
    if (level === 'error' || level === 'critical') return 'error';
    return 'info';
}

function passesFilter(entry) {
    if (logFilter === 'all') return true;
    const g = levelGroup(entry.level);
    return logFilter === 'warn' ? (g === 'warn' || g === 'error') : g === 'error';
}

function renderLog() {
    const box = $('st-log');
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const lines = allLogs.filter(passesFilter).filter(e => e.level !== 'debug');
    if (!lines.length) {
        box.innerHTML = '<div class="st-log-empty">Nothing to show.</div>';
        return;
    }
    box.innerHTML = lines.map(e => {
        const d = parseUTC(e.ts);
        const time = d ? d.toLocaleTimeString([], { hour12: false }) : '';
        return `<div class="st-log-line ${esc(e.level)}"><span class="t">${esc(time)}</span><span class="src">${e.source === 'box' ? 'box' : 'app'}</span><span class="m">${esc(e.message)}</span></div>`;
    }).join('');
    if (nearBottom) box.scrollTop = box.scrollHeight;
}

async function pollLogs() {
    try {
        const res = await fetch('/api/logs' + (lastLogId ? `?after=${lastLogId}` : '?limit=200'));
        if (!res.ok) return;
        const data = await res.json();
        if (data.logs && data.logs.length) {
            allLogs = allLogs.concat(data.logs).slice(-MAX_LOG_LINES);
            lastLogId = data.logs[data.logs.length - 1].id;
            renderLog();
            const box = $('st-log');
            if (data.logs.length === allLogs.length) box.scrollTop = box.scrollHeight;
        }
    } catch (e) { /* keep polling */ }
}

// ─── Data + actions ───────────────────────────────────────────────────────────

async function pollStatus() {
    try {
        const res = await fetch('/api/status');
        if (res.status === 401) {
            $('st-login').classList.remove('st-hidden');
            $('st-content').classList.add('st-hidden');
            return;
        }
        $('st-login').classList.add('st-hidden');
        $('st-content').classList.remove('st-hidden');
        render(await res.json());
    } catch (e) {
        $('st-updated').textContent = 'Cannot reach the web server - retrying...';
    }
}

async function sendCommand(cmd, btn) {
    if (cmd === 'restart_agent' && !confirm('Restart the box software? Printing is interrupted for about 10 seconds.')) return;
    if (lastData && !lastData.online) { toast('The box is offline - it will run this when it comes back.'); }
    btn.disabled = true;
    try {
        const res = await fetch('/api/command', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd })
        });
        toast(res.ok ? 'Sent - the box will do it within ~10 seconds. Watch the activity log.' : 'Could not send the action.');
        if (res.ok && cmd === 'test_speaker') showSpeakerPrompt();
        setTimeout(pollLogs, 1500);
    } catch (e) { toast('Connection error'); }
    setTimeout(() => { btn.disabled = false; }, 4000);
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-cmd]').forEach(b => b.addEventListener('click', () => sendCommand(b.dataset.cmd, b)));
    document.querySelectorAll('#st-chips .st-chip').forEach(chip => chip.addEventListener('click', () => {
        document.querySelectorAll('#st-chips .st-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        logFilter = chip.dataset.level;
        renderLog();
    }));
    $('st-copy').addEventListener('click', async () => {
        const text = allLogs.filter(passesFilter).map(e => `${e.ts} [${e.level}] ${e.source}: ${e.message}`).join('\n');
        try { await navigator.clipboard.writeText(text); toast('Log copied'); } catch (e) { toast('Copy failed'); }
    });
    pollStatus();
    pollLogs();
    setInterval(pollStatus, STATUS_POLL_MS);
    setInterval(pollLogs, LOG_POLL_MS);
});

// ─── Speaker confirmation: the audio jack can't tell us if the speaker is on, so ask a human ───
function showSpeakerPrompt() {
    const box = $('st-speaker-prompt');
    box.classList.remove('st-hidden');
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function answerSpeaker(ok) {
    $('st-speaker-prompt').classList.add('st-hidden');
    try {
        await fetch('/api/speaker-confirm', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ok })
        });
        toast(ok ? 'Great - speaker confirmed.' : 'Noted - check the speaker is on and the cable is plugged in.');
        pollStatus();
        setTimeout(pollLogs, 800);
    } catch (e) { toast('Connection error'); }
}

document.addEventListener('DOMContentLoaded', () => {
    $('st-heard-yes').addEventListener('click', () => answerSpeaker(true));
    $('st-heard-no').addEventListener('click', () => answerSpeaker(false));
});
