import { Room, RoomEvent, Track } from "https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.esm.mjs";

const wsUrlInput = document.getElementById("wsUrl");
const roomNameInput = document.getElementById("roomName");
const identityInput = document.getElementById("identity");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const muteBtn = document.getElementById("muteBtn");
const transcriptEl = document.getElementById("transcript");
const logEl = document.getElementById("log");
const remoteAudio = document.getElementById("remoteAudio");
const connectionStateEl = document.getElementById("connectionState");
const micStateEl = document.getElementById("micState");
const remoteStateEl = document.getElementById("remoteState");

let room = null;
let micMuted = false;

const appendLog = (message) => {
  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  logEl.prepend(entry);
};

const appendTranscript = (speaker, text) => {
  const entry = document.createElement("div");
  entry.className = "transcript-entry";
  entry.innerHTML = `<span class="speaker">${speaker}</span><span>${text}</span>`;
  transcriptEl.prepend(entry);
};

const updateButtons = (connected) => {
  connectBtn.disabled = connected;
  disconnectBtn.disabled = !connected;
  muteBtn.disabled = !connected;
};

const setConnectionState = (text) => { connectionStateEl.textContent = text; };
const setMicState = (text) => { micStateEl.textContent = text; };
const setRemoteState = (text) => { remoteStateEl.textContent = text; };

const cleanupTracks = () => {
  remoteAudio.srcObject = null;
  setRemoteState("无");
};

const loadDefaults = async () => {
  const resp = await fetch("/defaults");
  const data = await resp.json();
  wsUrlInput.value = data.ws_url;
  roomNameInput.value = data.room;
  identityInput.value = data.identity;
};

const applyTrack = (track) => {
  if (track.kind !== Track.Kind.Audio) {
    return;
  }
  const audioEl = track.attach();
  remoteAudio.srcObject = audioEl.srcObject;
  setRemoteState("已接收");
  appendLog("已订阅远端音频轨道。");
};

const disconnect = async () => {
  if (!room) {
    return;
  }
  await room.disconnect();
  room = null;
  micMuted = false;
  updateButtons(false);
  setConnectionState("未连接");
  setMicState("未开启");
  cleanupTracks();
  appendLog("已断开连接。");
};

const connect = async () => {
  connectBtn.disabled = true;
  appendLog("正在请求 token 并连接 LiveKit...");

  const roomName = roomNameInput.value.trim();
  const identity = identityInput.value.trim();
  const tokenResp = await fetch(
    `/token?room=${encodeURIComponent(roomName)}&identity=${encodeURIComponent(identity)}`,
  );
  const tokenData = await tokenResp.json();

  room = new Room({
    adaptiveStream: true,
    dynacast: true,
    audioCaptureDefaults: {
      autoGainControl: true,
      echoCancellation: true,
      noiseSuppression: true,
    },
  });

  room
    .on(RoomEvent.Connected, () => {
      setConnectionState("已连接");
      appendLog("房间连接成功。");
    })
    .on(RoomEvent.Disconnected, () => {
      setConnectionState("未连接");
      cleanupTracks();
      appendLog("房间已断开。");
      updateButtons(false);
    })
    .on(RoomEvent.TrackSubscribed, (track) => {
      applyTrack(track);
    })
    .on(RoomEvent.TrackUnsubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        cleanupTracks();
      }
    })
    .on(RoomEvent.LocalTrackPublished, (publication) => {
      if (publication.kind === Track.Kind.Audio) {
        setMicState("已开启");
        appendLog("本地麦克风已发布。");
      }
    })
    .on(RoomEvent.TranscriptionReceived, (segments, participant) => {
      for (const segment of segments) {
        if (!segment.text?.trim()) {
          continue;
        }
        const speaker = participant?.isLocal ? "你" : (participant?.identity || "助手");
        appendTranscript(speaker, segment.text.trim());
      }
    });

  await room.connect(tokenData.ws_url, tokenData.token);
  await room.localParticipant.setMicrophoneEnabled(true);
  await room.startAudio();
  updateButtons(true);
};

connectBtn.addEventListener("click", async () => {
  try {
    await connect();
  } catch (error) {
    appendLog(`连接失败: ${error}`);
    updateButtons(false);
    setConnectionState("失败");
  }
});

disconnectBtn.addEventListener("click", async () => {
  await disconnect();
});

muteBtn.addEventListener("click", async () => {
  if (!room) {
    return;
  }
  micMuted = !micMuted;
  await room.localParticipant.setMicrophoneEnabled(!micMuted);
  setMicState(micMuted ? "已静音" : "已开启");
  muteBtn.textContent = micMuted ? "取消静音" : "麦克风静音";
  appendLog(micMuted ? "麦克风已静音。" : "麦克风已恢复。");
});

await loadDefaults();
appendLog("页面已就绪。");
