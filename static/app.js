// ── DOM refs ─────────────────────────────────────────────────────────
var fileInput = document.getElementById('fileInput');
var uploadBtn = document.getElementById('uploadBtn');
var fileInfo = document.getElementById('fileInfo');
var btnRun = document.getElementById('btnRun');
var progressPanel = document.getElementById('progressPanel');
var progressFill = document.getElementById('progressFill');
var progressLabel = document.getElementById('progressLabel');
var progressPct = document.getElementById('progressPct');
var progressElapsed = document.getElementById('progressElapsed');
var progressDuration = document.getElementById('progressDuration');
var progressWords = document.getElementById('progressWords');
var logContainer = document.getElementById('logContainer');
var errorEl = document.getElementById('error');
var resultsEl = document.getElementById('results');
var jobsPanel = document.getElementById('jobsPanel');
var jobsList = document.getElementById('jobsList');
var btnStop = document.getElementById('btnStop');
var stoppedOverlay = document.getElementById('stoppedOverlay');

var selectedFile = null;
var currentJobId = null;
var startTime = null;
var elapsedInterval = null;
var lastLogCount = 0;
var serverStopped = false;

var STAGE_LABELS = {
  'upload': 'Processing upload...',
  'queued': 'Queued — waiting for another job to finish...',
  'info': 'Analyzing audio...',
  'splitting': 'Trimming silence + chunking...',
  'transcribing': 'Transcribing on Apple Silicon...',
  'transcription_done': 'Transcription complete',
  'diarizing': 'Identifying speakers...',
  'warning': 'Partial failure — continuing',
  'done': 'Complete!',
  'error': 'Error',
};

// ── File selection ───────────────────────────────────────────────────
uploadBtn.addEventListener('click', function() { fileInput.click(); });
fileInput.addEventListener('change', function() {
  if (fileInput.files.length) pickFile(fileInput.files[0]);
});

function pickFile(file) {
  selectedFile = file;
  var mb = (file.size / 1024 / 1024).toFixed(1);
  fileInfo.innerHTML = '<span>' + escapeHtml(file.name) +
    '</span> <span class="size">(' + mb + ' MB)</span>';
  btnRun.disabled = false;
  resultsEl.classList.remove('visible');
  errorEl.classList.remove('visible');
}

// ── Run ──────────────────────────────────────────────────────────────
btnRun.addEventListener('click', function() { run(); });

async function run() {
  if (!selectedFile) return;

  // Reset UI
  btnRun.disabled = true;
  resultsEl.classList.remove('visible');
  errorEl.classList.remove('visible');
  errorEl.style.background = '';
  errorEl.style.borderColor = '';
  errorEl.style.color = '';
  errorEl.innerHTML = '';
  logContainer.innerHTML = '';
  progressFill.style.width = '0%';
  progressPct.textContent = '0%';
  progressLabel.textContent = 'Uploading file...';
  progressDuration.textContent = '';
  progressWords.textContent = '';
  progressPanel.classList.add('visible');
  lastLogCount = 0;

  startTime = Date.now();
  if (elapsedInterval) clearInterval(elapsedInterval);
  elapsedInterval = setInterval(updateElapsed, 1000);
  updateElapsed();

  var form = new FormData();
  form.append('file', selectedFile);
  form.append('language', document.getElementById('language').value);
  if (document.getElementById('optDiarize').checked) form.append('diarize', 'true');

  try {
    var res = await fetch('/api/process', { method: 'POST', body: form });
    var data = await res.json();
    if (data.error) { showError(data.error); return; }
    currentJobId = data.job_id;
    pollStatus();
  } catch (err) {
    showError('Upload failed: ' + err.message);
  }
}

// ── Polling ──────────────────────────────────────────────────────────
function pollStatus() {
  if (!currentJobId || serverStopped) return;

  fetch('/api/status/' + currentJobId)
    .then(function(res) { return res.json(); })
    .then(function(job) {
      progressFill.style.width = job.percent + '%';
      progressPct.textContent = job.percent + '%';
      progressLabel.textContent = STAGE_LABELS[job.stage] || job.stage;

      if (job.duration_min) {
        progressDuration.textContent = 'Duration: ' + job.duration_min + ' min';
      }
      if (job.word_count) {
        progressWords.textContent = 'Words: ' + job.word_count.toLocaleString();
      }

      // Append any new log entries
      if (job.log && job.log.length > lastLogCount) {
        for (var i = lastLogCount; i < job.log.length; i++) {
          addLogEntry(job.log[i]);
        }
        lastLogCount = job.log.length;
        logContainer.scrollTop = logContainer.scrollHeight;
      }

      if (job.status === 'done') {
        clearInterval(elapsedInterval);
        fetchResults();
        return;
      }
      if (job.status === 'error') {
        clearInterval(elapsedInterval);
        // Try to fetch a partial transcript if there is one
        if (job.has_transcript) {
          fetchResults();
        } else {
          showError(job.error || 'Unknown error');
        }
        return;
      }

      setTimeout(pollStatus, 2000);
    })
    .catch(function() {
      if (serverStopped) return;
      setTimeout(pollStatus, 3000);
    });
}

function fetchResults() {
  fetch('/api/results/' + currentJobId)
    .then(function(res) { return res.json(); })
    .then(function(data) {
      renderTranscript(data.transcript || '');

      // Surface warnings or hard errors
      var notes = [];
      if (data.warnings && data.warnings.length) {
        notes = notes.concat(data.warnings);
      }
      if (data.status === 'error' && data.error) {
        notes.push('Error during pipeline: ' + data.error);
      }
      if (notes.length) {
        var html = '<strong>Heads up:</strong><ul style="margin: 0.5rem 0 0 1.25rem;">';
        notes.forEach(function(n) { html += '<li>' + escapeHtml(n) + '</li>'; });
        html += '</ul>';
        errorEl.innerHTML = html;
        errorEl.style.background = 'rgba(251, 191, 36, 0.08)';
        errorEl.style.borderColor = 'rgba(251, 191, 36, 0.25)';
        errorEl.style.color = 'var(--amber)';
        errorEl.classList.add('visible');
      }

      document.getElementById('exportMd').onclick = function() {
        window.location.href = '/api/export/' + currentJobId + '/md';
      };
      document.getElementById('exportTxt').onclick = function() {
        window.location.href = '/api/export/' + currentJobId + '/txt';
      };
      document.getElementById('exportJson').onclick = function() {
        window.location.href = '/api/export/' + currentJobId + '/json';
      };

      resultsEl.classList.add('visible');
      btnRun.disabled = false;
      lastLogCount = 0;
      refreshJobs();
    });
}

// ── Recent jobs ──────────────────────────────────────────────────────
function refreshJobs() {
  if (serverStopped) return;
  fetch('/api/jobs').then(function(res) { return res.json(); }).then(function(data) {
    if (!data.jobs || !data.jobs.length) {
      // Empty screen: the mark's sound bars, quiet, beside empty text lines.
      jobsPanel.style.display = 'block';
      jobsList.innerHTML =
        '<div class="empty-state">' +
          '<svg class="empty-art" viewBox="0 0 180 120" aria-hidden="true">' +
            '<g fill="#6ee7a0">' +
              '<rect x="22" y="57" width="6" height="6" rx="3"/>' +
              '<rect x="34" y="55" width="6" height="10" rx="3" opacity="0.8"/>' +
              '<rect x="46" y="57" width="6" height="6" rx="3" opacity="0.6"/>' +
              '<rect x="58" y="58" width="6" height="4" rx="2" opacity="0.45"/>' +
              '<rect x="70" y="58" width="6" height="4" rx="2" opacity="0.3"/>' +
            '</g>' +
            '<g fill="none" stroke="#3a3c47" stroke-width="2.5" stroke-dasharray="4 5" stroke-linecap="round">' +
              '<path d="M96 40 H158"/><path d="M96 54 H146"/><path d="M96 68 H154"/><path d="M96 82 H130"/>' +
            '</g>' +
          '</svg>' +
          '<h3>No recordings yet</h3>' +
          '<p>Choose a meeting recording above. You get the transcript with each speaker labelled.</p>' +
        '</div>';
      return;
    }
    jobsPanel.style.display = 'block';
    var rows = data.jobs.map(function(j) {
      var statusClass = 'status-' + j.status;
      var meta = [];
      if (j.duration_min) meta.push(j.duration_min + ' min');
      if (j.word_count) meta.push(j.word_count.toLocaleString() + ' words');
      if (j.diarized) meta.push('speakers');
      var actions = (j.status === 'done' || j.status === 'error')
        ? '<a class="job-link" href="/api/export/' + j.id + '/md">md</a>' +
          '<a class="job-link" href="/api/export/' + j.id + '/txt">txt</a>' +
          '<a class="job-link" href="/api/export/' + j.id + '/json">json</a>'
        : '<span class="job-status ' + statusClass + '">' + j.status + '</span>';
      return '<div class="job-row">' +
        '<div class="job-main">' +
          '<div class="job-name">' + escapeHtml(j.filename || j.id) + '</div>' +
          '<div class="job-meta">' + escapeHtml(meta.join(' · ')) +
            ' · <span class="job-time">' + escapeHtml(j.created_at) + '</span></div>' +
        '</div>' +
        '<div class="job-actions">' + actions + '</div>' +
      '</div>';
    });
    jobsList.innerHTML = rows.join('');
  });
}

// ── Stop the server ──────────────────────────────────────────────────
// Guarded: if a cached/older template is served without the footer button,
// a missing element must not break the rest of the page.
if (btnStop) {
  btnStop.addEventListener('click', function() { stopServer(false); });
}

function stopServer(force) {
  var prompt = force
    ? 'A transcription is still running. Stopping now loses that job\u2019s progress \u2014 the transcript is only saved when it finishes.\n\nStop anyway?'
    : 'Stop Meeting Transcriber? Open it again from the Meeting Transcriber app.';
  if (!confirm(prompt)) return;

  btnStop.disabled = true;
  fetch('/api/shutdown' + (force ? '?force=true' : ''), { method: 'POST' })
    .then(function(res) {
      return res.json().then(function(data) { return { status: res.status, data: data }; });
    })
    .then(function(r) {
      if (r.status === 409 && r.data.busy) {
        // Server refused because a job is in flight — re-ask with a warning.
        btnStop.disabled = false;
        stopServer(true);
        return;
      }
      if (r.data.stopping) {
        serverStopped = true;
        clearInterval(elapsedInterval);
        if (stoppedOverlay) stoppedOverlay.classList.add('visible');
      } else {
        btnStop.disabled = false;
        showError(r.data.error || 'Could not stop the server.');
      }
    })
    .catch(function() {
      // The process may have exited before the response reached us.
      serverStopped = true;
      clearInterval(elapsedInterval);
      if (stoppedOverlay) stoppedOverlay.classList.add('visible');
    });
}

// Show recent jobs on first load
refreshJobs();

// ── Helpers ──────────────────────────────────────────────────────────

function updateElapsed() {
  if (!startTime) return;
  var secs = Math.floor((Date.now() - startTime) / 1000);
  var m = Math.floor(secs / 60);
  var s = secs % 60;
  progressElapsed.textContent = 'Elapsed: ' + m + 'm ' + (s < 10 ? '0' : '') + s + 's';
}

function addLogEntry(entry) {
  var div = document.createElement('div');
  div.className = 'log-entry';
  div.setAttribute('data-stage', entry.stage);
  div.innerHTML =
    '<span class="log-time">' + escapeHtml(entry.time) + '</span>' +
    '<span class="log-stage">' + escapeHtml(entry.stage) + '</span>' +
    '<span class="log-msg">' + escapeHtml(entry.message) + '</span>';
  logContainer.appendChild(div);
}

function showError(msg) {
  clearInterval(elapsedInterval);
  errorEl.style.background = '';
  errorEl.style.borderColor = '';
  errorEl.style.color = '';
  errorEl.textContent = msg;
  errorEl.classList.add('visible');
  progressPanel.classList.remove('visible');
  btnRun.disabled = false;
  lastLogCount = 0;
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Transcript, "Document" look (11 Nov) ─────────────────────────────
// Paragraphs come as "[hh:mm:ss] Speaker A: text" (with speakers) or plain text (without).
// Each speaker gets a colour in order of first appearance; the time sits in the margin.
var lastTranscript = '';
var SPEAKER_COLOURS = 6;

function shortTime(t) {                 // "00:12:04" -> "12:04", "01:02:03" -> "1:02:03"
  var p = t.split(':');
  return p[0] === '00' ? p[1] + ':' + p[2] : String(Number(p[0])) + ':' + p[1] + ':' + p[2];
}

function renderTranscript(text) {
  lastTranscript = text;
  var body = document.getElementById('transcriptBody');
  body.textContent = '';
  var speakers = {};
  text.split(/\n{2,}/).forEach(function(para) {
    para = para.trim();
    if (!para) return;
    var m = para.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+([^:\n]{1,40}):\s+([\s\S]*)$/);
    var p = document.createElement('div');
    p.className = 'doc-p';
    var time = document.createElement('time');
    var who = null, words = para;
    if (m) {
      time.textContent = shortTime(m[1]);
      who = m[2].trim();
      words = m[3];
      if (!(who in speakers)) speakers[who] = Object.keys(speakers).length % SPEAKER_COLOURS;
    } else {
      var t = para.match(/^\[(\d{2}:\d{2}:\d{2})\]\s+([\s\S]*)$/);
      if (t) { time.textContent = shortTime(t[1]); words = t[2]; }
    }
    p.appendChild(time);
    var main = document.createElement('div');
    if (who) {
      var name = document.createElement('b');
      name.className = 'doc-who s' + speakers[who];
      name.textContent = who;
      main.appendChild(name);
    }
    var w = document.createElement('p');
    w.textContent = words;
    main.appendChild(w);
    p.appendChild(main);
    body.appendChild(p);
  });
}

function copyContent(id) {
  var el = document.getElementById(id);
  var text = id === 'transcriptBody' && lastTranscript ? lastTranscript : (el.innerText || el.textContent);
  navigator.clipboard.writeText(text).then(function() {
    var btn = el.closest('.panel').querySelector('.copy-btn');
    if (btn) {
      var orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(function() { btn.textContent = orig; }, 1500);
    }
  });
}
