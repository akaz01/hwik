'use strict';

/* 휴대폰 화면: 고른 파일을 차례로 PC에 보내고, 보내는 중인지 다 보냈는지를 크게 보여 준다. */

const MB = 1024 * 1024;
const GB = 1024 * MB;
const SPEED_SETTLE_MS = 800; // 처음 잠깐은 속도가 들쭉날쭉해 남은 시간을 보여 주지 않는다

const TEXT = {
  idleHeadline: '보낼 파일을\n골라 주세요',
  idleDetail: '사진, 영상, 문서 모두 보낼 수 있습니다.',
  pick: '사진·파일 고르기',
  pickMore: '더 보내기',
  hint: '고르면 바로 PC로 보냅니다.',
  keepOpen: '다 보낼 때까지 이 화면을 켜 두세요.',
  doneDetail: 'PC에서 확인하세요.',
  cancelled: '보내기를 취소했습니다.',
  linked: 'PC와 연결됨',
  unlinked: 'PC와 연결 안 됨',
  lost: 'PC와 연결이 끊겼습니다. 같은 와이파이(또는 핫스팟)인지 확인하고, PC에서 QR을 다시 찍어 주세요.',
  expired: '이 화면은 더 쓸 수 없습니다. PC에서 QR을 다시 찍어 주세요.',
  refused: 'PC가 이 파일을 받지 않았습니다.',
  tooLarge: '파일이 너무 커서 보내지 않았습니다.',
  badName: '파일 이름을 읽을 수 없어 보내지 않았습니다.',
  broken: '보내는 중 문제가 생겼습니다. 다시 골라 주세요.',
  lostHeadline: 'PC와 연결이\n끊겼습니다',
  fromPcHeadline: 'PC에서 보낸 것이\n있습니다',
  fromPcDetail: '아래 "PC에서 온 것"에서 받아 주세요.',
  take: '받기',
  copy: '복사',
  copied: '복사했습니다',
  copyByHand: '길게 눌러 복사하세요',
  noteSent: 'PC로 보냈습니다. PC에서 Ctrl+V로 붙여넣을 수 있습니다.',
  noteEmpty: '보낼 글자를 먼저 써 주세요.',
  noteSending: '보내는 중…',
};

const POLL_MS = 1500; // PC가 보낸 것이 있는지 물어보는 간격
const POLL_FAILURES_BEFORE_LOST = 3;
const POLL_TIMEOUT_MS = 4000;

const el = {
  body: document.body,
  stage: document.querySelector('.stage'),
  link: document.getElementById('link'),
  headline: document.getElementById('headline'),
  detail: document.getElementById('detail'),
  cancel: document.getElementById('cancel'),
  picker: document.getElementById('picker'),
  pickLabel: document.getElementById('pick-label'),
  hint: document.getElementById('hint'),
  sent: document.getElementById('sent'),
  sentList: document.getElementById('sent-list'),
  inbox: document.getElementById('inbox'),
  inboxList: document.getElementById('inbox-list'),
  noteText: document.getElementById('note-text'),
  noteSend: document.getElementById('note-send'),
  noteStatus: document.getElementById('note-status'),
};

let activeRequest = null;
let cancelRequested = false;
let maxFileBytes = Infinity; // PC가 받는 크기 한도. 화면을 열 때 PC에 물어본다

function formatSize(bytes) {
  if (bytes >= GB) return (bytes / GB).toFixed(1) + 'GB';
  if (bytes >= MB) return (bytes / MB).toFixed(1) + 'MB';
  return Math.max(1, Math.round(bytes / 1024)) + 'KB';
}

function formatRemaining(seconds) {
  if (seconds < 5) return '곧 끝남';
  if (seconds <= 55) return '약 ' + Math.ceil(seconds / 5) * 5 + '초 남음'; // PC 화면(batch.py)과 같은 기준
  return '약 ' + Math.ceil(seconds / 60) + '분 남음';
}

function showStage(view) {
  el.body.dataset.state = view.state;
  el.headline.textContent = view.headline;
  el.detail.textContent = view.detail;
  el.stage.style.setProperty('--progress', String(view.progress || 0));
  el.cancel.hidden = view.state !== 'sending';
  el.picker.disabled = view.state === 'sending';
  el.link.textContent = view.linked === false ? TEXT.unlinked : TEXT.linked;
  el.pickLabel.textContent = view.state === 'idle' ? TEXT.pick : TEXT.pickMore;
  el.hint.textContent = view.state === 'sending' ? TEXT.keepOpen : TEXT.hint;
}

function addSentItem(name, note, failed) {
  const item = document.createElement('li');
  item.className = failed ? 'sent__item sent__item--failed' : 'sent__item';
  const mark = document.createElement('span');
  mark.className = 'sent__mark';
  mark.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.className = 'sent__name';
  label.textContent = name; // 파일 이름은 글자로만 넣는다(HTML로 해석하지 않음)
  const detail = document.createElement('span');
  detail.className = 'sent__note';
  detail.textContent = note;
  item.append(mark, label, detail);
  el.sentList.prepend(item);
  el.sent.hidden = false;
}

function failureMessage(status, response) {
  if (response && typeof response.message === 'string' && response.message) return response.message;
  if (status === 403 || status === 404 || status === 429) return TEXT.expired;
  return TEXT.refused;
}

/* 파일 하나를 보낸다. 결과: {outcome: 'sent' | 'refused' | 'lost' | 'cancelled', message} */
function uploadOne(file, left, onProgress) {
  return new Promise((resolve) => {
    if (file.size > maxFileBytes) {
      resolve({ outcome: 'refused', message: TEXT.tooLarge });
      return;
    }
    let encodedName;
    try {
      encodedName = encodeURIComponent(file.name);
    } catch (error) {
      resolve({ outcome: 'refused', message: TEXT.badName }); // 깨진 글자가 든 이름
      return;
    }
    const request = new XMLHttpRequest();
    activeRequest = request;
    request.open('POST', 'up');
    request.responseType = 'json';
    request.setRequestHeader('X-Name', encodedName);
    // 뒤에 더 보낼 것을 알려, PC 화면도 전체 기준으로 남은 시간을 보여 주게 한다.
    request.setRequestHeader('X-Left-Count', String(left.count));
    request.setRequestHeader('X-Left-Bytes', String(left.bytes));
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onload = () => {
      if (request.status === 200) {
        resolve({ outcome: 'sent', message: '' });
      } else {
        const fatal = request.status === 403 || request.status === 404 || request.status === 429;
        resolve({ outcome: fatal ? 'lost' : 'refused', message: failureMessage(request.status, request.response) });
      }
    };
    request.onerror = () => resolve({ outcome: 'lost', message: TEXT.lost });
    request.ontimeout = () => resolve({ outcome: 'lost', message: TEXT.lost });
    request.onabort = () => resolve({ outcome: 'cancelled', message: TEXT.cancelled });
    request.send(file);
  });
}

function sendingView(index, count, file, sentBytes, totalBytes, startedAt, skippedBytes) {
  const elapsedMs = performance.now() - startedAt;
  // 속도는 실제로 보낸 것만으로 잰다: 못 보내고 넘어간 파일까지 넣으면 남은 시간이 너무 짧게 나온다.
  const speed = elapsedMs > 0 ? Math.max(sentBytes - skippedBytes, 0) / (elapsedMs / 1000) : 0;
  const parts = [file.name];
  if (elapsedMs > SPEED_SETTLE_MS && speed > 0) {
    parts.push('초당 ' + formatSize(speed) + ' · ' + formatRemaining((totalBytes - sentBytes) / speed));
  }
  return {
    state: 'sending',
    headline: count > 1 ? '보내는 중\n' + (index + 1) + ' / ' + count : '보내는 중',
    detail: parts.join('\n'),
    progress: totalBytes > 0 ? Math.min(sentBytes / totalBytes, 1) : 0,
  };
}

function resultView(sentCount, count, problem) {
  if (sentCount === count) {
    return { state: 'done', headline: sentCount + '개\n보냈습니다', detail: TEXT.doneDetail };
  }
  const headline = sentCount > 0 ? count + '개 중 ' + sentCount + '개만\n보냈습니다' : '보내지\n못했습니다';
  return { state: 'failed', headline, detail: problem.message, linked: problem.outcome !== 'lost' };
}

async function sendAll(files) {
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  const startedAt = performance.now();
  cancelRequested = false;
  let finishedBytes = 0;
  let skippedBytes = 0; // 보내지 못하고 넘어간 파일들의 크기
  let sentCount = 0;
  let problem = null;

  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    const report = (loaded) =>
      showStage(
        sendingView(index, files.length, file, finishedBytes + Math.min(loaded, file.size), totalBytes, startedAt, skippedBytes),
      );
    report(0);
    const later = files.slice(index + 1).filter((next) => next.size <= maxFileBytes); // 너무 큰 것은 어차피 안 보낸다
    const left = { count: later.length, bytes: later.reduce((sum, next) => sum + next.size, 0) };
    const result = await uploadOne(file, left, report);
    if (result.outcome === 'sent') {
      sentCount += 1;
      finishedBytes += file.size;
      addSentItem(file.name, formatSize(file.size), false);
      continue;
    }
    problem = result;
    finishedBytes += file.size; // 못 보낸 파일도 끝난 것으로 쳐야 진행 표시가 끝까지 간다
    skippedBytes += file.size;
    addSentItem(file.name, result.outcome === 'cancelled' ? '취소함' : '못 보냄', true);
    if (result.outcome !== 'refused' || cancelRequested) break; // 연결이 끊겼거나 취소했으면 나머지도 보내지 않는다
  }

  showStage(resultView(sentCount, files.length, problem || { message: '', outcome: 'sent' }));
}

async function sendPicked(files) {
  try {
    await sendAll(files);
  } catch (error) {
    // 예상하지 못한 오류가 나도 화면이 "보내는 중"에 멈춰 있지 않게 한다.
    showStage({ state: 'failed', headline: '보내지\n못했습니다', detail: TEXT.broken });
  } finally {
    activeRequest = null;
  }
}

el.picker.addEventListener('change', () => {
  const files = Array.from(el.picker.files || []);
  el.picker.value = ''; // 같은 파일을 다시 골라도 보내지게 비워 둔다
  if (files.length > 0) sendPicked(files);
});

/* ── PC에서 온 것: PC가 올려 둔 파일과 글자를 주기적으로 물어 와 보여 준다 ── */

let seenVersion = -1;
let pollFailures = 0;
let linkLost = false;

function isBusy() {
  return el.body.dataset.state === 'sending';
}

function legacyCopy(text) {
  // http 주소에서는 새 복사 기능을 쓸 수 없어, 보이지 않는 칸에 넣고 선택해 복사하는 옛 방법을 쓴다.
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.className = 'visually-hidden';
  document.body.append(area);
  area.select();
  area.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (error) {
    ok = false;
  }
  area.remove();
  return ok;
}

function copyText(text) {
  if (window.isSecureContext && navigator.clipboard) {
    return navigator.clipboard.writeText(text).then(
      () => true,
      () => legacyCopy(text),
    );
  }
  return Promise.resolve(legacyCopy(text));
}

function fileRow(item) {
  const row = document.createElement('li');
  row.className = 'inbox__item';
  const name = document.createElement('span');
  name.className = 'inbox__name';
  name.textContent = item.name;
  const size = document.createElement('span');
  size.className = 'inbox__size';
  size.textContent = formatSize(item.size);
  name.append(size);
  const take = document.createElement('a');
  take.className = 'inbox__action';
  take.href = 'dl/' + encodeURIComponent(item.id);
  take.download = item.name;
  take.textContent = TEXT.take;
  row.append(name, take);
  return row;
}

function textRow(item) {
  const row = document.createElement('li');
  row.className = 'inbox__item';
  const text = document.createElement('p');
  text.className = 'inbox__text';
  text.textContent = item.text; // 글자로만 넣는다(HTML로 해석하지 않음)
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'inbox__action';
  copy.textContent = TEXT.copy;
  copy.addEventListener('click', async () => {
    copy.textContent = (await copyText(item.text)) ? TEXT.copied : TEXT.copyByHand;
  });
  row.append(text, copy);
  return row;
}

function showInbox(items) {
  const rows = items
    .filter((item) => item && (item.kind === 'file' || item.kind === 'text'))
    .map((item) => (item.kind === 'file' ? fileRow(item) : textRow(item)))
    .reverse(); // 새로 온 것이 위로
  el.inboxList.replaceChildren(...rows);
  el.inbox.hidden = rows.length === 0;
  if (rows.length > 0 && el.body.dataset.state === 'idle') {
    showStage({ state: 'idle', headline: TEXT.fromPcHeadline, detail: TEXT.fromPcDetail });
  }
}

function markLinkLost() {
  linkLost = true;
  if (!isBusy()) {
    showStage({ state: 'failed', headline: TEXT.lostHeadline, detail: TEXT.lost, linked: false });
  }
}

function markLinkBack() {
  if (!linkLost) return;
  linkLost = false;
  if (!isBusy()) showStage({ state: 'idle', headline: TEXT.idleHeadline, detail: TEXT.idleDetail });
}

async function pollOnce() {
  // PC가 꺼지거나 와이파이가 사라지면 답도 오류도 없이 오래 걸릴 수 있어, 기다리는 시간을 정해 둔다.
  const giveUp = new AbortController();
  const timer = setTimeout(() => giveUp.abort(), POLL_TIMEOUT_MS);
  try {
    // 이미 받은 목록의 번호를 알려, 바뀐 것이 없으면 PC가 목록(글자 내용)을 다시 보내지 않게 한다.
    const response = await fetch('state', {
      cache: 'no-store',
      signal: giveUp.signal,
      headers: { 'X-Seen': String(seenVersion) },
    });
    if (!response.ok) throw new Error('refused');
    const state = await response.json();
    pollFailures = 0;
    markLinkBack();
    if (state.version !== seenVersion && Array.isArray(state.items)) {
      seenVersion = state.version;
      showInbox(state.items);
    }
  } catch (error) {
    pollFailures += 1;
    if (pollFailures === POLL_FAILURES_BEFORE_LOST) markLinkLost();
  } finally {
    clearTimeout(timer);
  }
}

async function pollLoop() {
  if (!document.hidden) await pollOnce(); // 화면이 꺼져 있거나 다른 탭을 볼 때는 쉰다
  setTimeout(pollLoop, POLL_MS);
}

/* ── PC로 글자 보내기 ── */

function showNoteStatus(message, failed) {
  el.noteStatus.textContent = message;
  el.noteStatus.className = failed ? 'note__status note__status--failed' : 'note__status';
}

async function sendNote() {
  const text = el.noteText.value;
  if (!text.trim()) {
    showNoteStatus(TEXT.noteEmpty, true);
    return;
  }
  el.noteSend.disabled = true;
  showNoteStatus(TEXT.noteSending, false);
  try {
    const response = await fetch('text', { method: 'POST', body: text });
    if (response.ok) {
      el.noteText.value = '';
      showNoteStatus(TEXT.noteSent, false);
    } else {
      const reply = await response.json().catch(() => null);
      showNoteStatus(failureMessage(response.status, reply), true);
    }
  } catch (error) {
    showNoteStatus(TEXT.lost, true);
  } finally {
    el.noteSend.disabled = false;
  }
}

el.noteSend.addEventListener('click', sendNote);
pollLoop();

fetch('info')
  .then((response) => (response.ok ? response.json() : null))
  .then((info) => {
    if (info && typeof info.maxFileBytes === 'number') maxFileBytes = info.maxFileBytes;
  })
  .catch(() => {}); // 못 물어봐도 보낼 수는 있다. 한도는 PC가 다시 확인한다

el.cancel.addEventListener('click', () => {
  cancelRequested = true;
  if (activeRequest) activeRequest.abort();
});

window.addEventListener('beforeunload', (event) => {
  if (el.body.dataset.state === 'sending') event.preventDefault();
});

showStage({ state: 'idle', headline: TEXT.idleHeadline, detail: TEXT.idleDetail });
