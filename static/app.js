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
// Two different jobs, deliberately kept apart:
//   liveJobId   - the transcription running now, driving the progress panel
//   viewedJobId - the recording whose transcript is on screen, and what the
//                 export buttons download
// They are usually the same, but opening a past recording while something is
// still transcribing must not stop tracking the live one.
var liveJobId = null;
var viewedJobId = null;
var startTime = null;
var elapsedInterval = null;
var lastLogCount = 0;
var serverStopped = false;

var STAGE_LABELS = {
  'upload': 'Processing upload...',
  'queued': 'Queued — waiting for another job to finish...',
  'info': 'Analyzing audio...',
  'splitting': 'Trimming silence + chunking...',
  'transcribing': 'Transcribing...',
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
  progressPanel.classList.remove('finished');
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
    liveJobId = data.job_id;
    viewedJobId = null;
    pollStatus(liveJobId);
  } catch (err) {
    showError('Upload failed: ' + err.message);
  }
}

// ── Polling ──────────────────────────────────────────────────────────
function pollStatus(jobId) {
  // A poll loop belongs to the job that started it. If that job is no longer
  // the live one, the loop must stop -- otherwise it appends another job's
  // log lines under this one and overwrites the header.
  if (jobId === undefined) jobId = liveJobId;
  if (!jobId || jobId !== liveJobId || serverStopped) return;

  fetch('/api/status/' + jobId)
    .then(function(res) { return res.json(); })
    .then(function(job) {
      // The fetch may have resolved after the user clicked away.
      if (jobId !== liveJobId || serverStopped) return;

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
        finishLiveJob(jobId, null);
        return;
      }
      if (job.status === 'error') {
        // A partial transcript is still worth showing.
        finishLiveJob(jobId, job.has_transcript ? null : (job.error || 'Unknown error'));
        return;
      }

      setTimeout(function() { pollStatus(jobId); }, 2000);
    })
    .catch(function() {
      if (serverStopped) return;
      setTimeout(function() { pollStatus(jobId); }, 3000);
    });
}

// The live job ended: wind the progress panel down and, unless the user is
// reading some other recording, open its transcript.
function finishLiveJob(jobId, errorMessage) {
  clearInterval(elapsedInterval);
  progressPanel.classList.add('finished');   // stop the spinner
  liveJobId = null;
  btnRun.disabled = false;
  lastLogCount = 0;
  refreshJobs();

  if (errorMessage) {
    showError(errorMessage);
    return;
  }
  // Don't yank the user away from a recording they opened while this ran.
  if (!viewedJobId || viewedJobId === jobId) {
    viewedJobId = jobId;
    fetchResults(jobId);
  }
}

function fetchResults(jobId) {
  if (!jobId) return;
  fetch('/api/results/' + jobId)
    .then(function(res) { return res.json(); })
    .then(function(data) {
      renderTranscript(data.transcript || '');
      resultsEl.classList.toggle('empty', !data.transcript);   // nothing to copy or export
      if (!data.transcript && data.status === 'error') {
        document.getElementById('transcriptBody').innerHTML = '<p class="doc-none">No transcript: this recording failed. The reason is above.</p>';
      }
      showDocHead(data);

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
        window.location.href = '/api/export/' + jobId + '/md';
      };
      document.getElementById('exportTxt').onclick = function() {
        window.location.href = '/api/export/' + jobId + '/txt';
      };
      document.getElementById('exportJson').onclick = function() {
        window.location.href = '/api/export/' + jobId + '/json';
      };

      resultsEl.classList.add('visible');
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
      if (j.status === 'error') meta.push('failed');
      var actions = (j.status === 'done' || j.status === 'error')
        ? '<a class="job-link" href="/api/export/' + j.id + '/md">md</a>' +
          '<a class="job-link" href="/api/export/' + j.id + '/txt">txt</a>' +
          '<a class="job-link" href="/api/export/' + j.id + '/json">json</a>'
        : '<span class="job-status ' + statusClass + '">' + j.status + '</span>';
      var openable = j.status === 'done' || j.status === 'error';
      meta.unshift(shortDate(j.created_at));
      return '<div class="job-row' + (openable ? ' openable' : '') + '"' +
          (openable ? ' role="button" tabindex="0" data-job="' + escapeHtml(j.id) + '"' : '') + '>' +
        '<div class="job-main">' +
          '<div class="job-name">' + escapeHtml(titleOf(j.filename || j.id)) + '</div>' +
          '<div class="job-meta">' + escapeHtml(meta.join(' · ')) + '</div>' +
        '</div>' +
        '<div class="job-actions">' + actions + '</div>' +
      '</div>';
    });
    jobsList.innerHTML = rows.join('');
    jobsList.querySelectorAll('.job-row.openable').forEach(function(row) {
      function open(e) {
        if (e.target.closest('.job-actions')) return;      // the md/txt/json links download
        openJob(row.getAttribute('data-job'));
      }
      row.addEventListener('click', open);
      row.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(e); } });
    });
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

// ── Reattach to a job that is still running ──────────────────────────
// liveJobId only ever gets set by starting a job in this tab, so a reload
// (or a second tab, or another device) used to lose sight of a transcription
// still running on the server: pollStatus() would return immediately and no
// progress was shown. Pick the live job back up on load.
function reattachRunningJob() {
  fetch('/api/jobs')
    .then(function(res) { return res.json(); })
    .then(function(data) {
      var jobs = (data && data.jobs) || [];
      var live = null;
      for (var i = 0; i < jobs.length; i++) {
        if (jobs[i].status === 'running' || jobs[i].status === 'queued') {
          live = jobs[i];
          break;
        }
      }
      if (!live) return;

      liveJobId = live.id;
      lastLogCount = 0;
      logContainer.innerHTML = '';
      if (live.filename) {
        fileInfo.innerHTML = '<span>' + escapeHtml(live.filename) + '</span>';
      }
      progressPanel.classList.remove('finished');
      progressPanel.classList.add('visible');
      btnRun.disabled = true;

      // Count elapsed from when the job was created, not from page load.
      // created_at has no timezone, so fall back if it parses to something
      // absurd (clock skew between the container and this browser).
      var created = live.created_at ? new Date(live.created_at).getTime() : NaN;
      var age = Date.now() - created;
      startTime = (isFinite(created) && age >= 0 && age < 86400000)
        ? created
        : Date.now();
      if (elapsedInterval) clearInterval(elapsedInterval);
      elapsedInterval = setInterval(updateElapsed, 1000);
      updateElapsed();

      pollStatus(liveJobId);
    })
    .catch(function() { /* offline or still starting: nothing to reattach */ });
}

// Show recent jobs on first load, and resume any job still in flight.
refreshJobs();
reattachRunningJob();

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

// ── Opening a past recording, and the title above the transcript ───────────
var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function shortDate(iso) {               // "2026-11-02T16:36:30" -> "2 Nov" (this year) or "2 Nov 2025"
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  if (!m) return iso || '';
  var s = Number(m[3]) + ' ' + MONTHS[Number(m[2]) - 1];
  return Number(m[1]) === new Date().getFullYear() ? s : s + ' ' + m[1];
}
function titleOf(filename) { return String(filename).replace(/\.[A-Za-z0-9]{2,4}$/, ''); }

function showDocHead(data) {
  document.getElementById('docTitle').textContent = titleOf(data.filename || 'Transcript');
  var meta = [];
  if (data.duration_min) meta.push(data.duration_min + ' min');
  if (data.word_count) meta.push(data.word_count.toLocaleString() + ' words');
  var speakers = {};
  (lastTranscript.match(/^\[\d{2}:\d{2}:\d{2}\]\s+([^:\n]{1,40}):/gm) || []).forEach(function(l) { speakers[l.replace(/^\[[^\]]*\]\s+/, '')] = 1; });
  var n = Object.keys(speakers).length;
  if (n) meta.push(n + ' speaker' + (n === 1 ? '' : 's'));
  if (data.language) meta.push(data.language === 'ro' ? 'Romanian' : data.language === 'en' ? 'English' : data.language);
  document.getElementById('docMeta').textContent = meta.join(' · ');
}

// "‹ Recordings" closes the document and goes back to the list.
document.getElementById('docBack').addEventListener('click', function(e) {
  e.preventDefault();
  resultsEl.classList.remove('visible');
  errorEl.classList.remove('visible');
  jobsPanel.scrollIntoView({behavior: 'smooth', block: 'start'});
});

function openJob(id) {
  // Only changes what is displayed. A transcription still running keeps its
  // progress panel and keeps polling, because it is tracked separately.
  viewedJobId = id;
  errorEl.classList.remove('visible');
  fetchResults(id);
  setTimeout(function() { resultsEl.scrollIntoView({behavior: 'smooth', block: 'start'}); }, 150);
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
