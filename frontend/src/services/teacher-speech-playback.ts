export type SpeechPlaybackState = "preparing" | "playing" | "paused" | "ended" | "blocked"

// AudioBuffer carries the source rate; Web Audio resamples for the device, including Safari.
export class TeacherSpeechPlayback {
  private readonly sources = new Set<AudioBufferSourceNode>()
  private nextStart = 0
  private pendingByte: number | undefined
  private complete = false
  private paused = false
  private stopped = false
  private hasAudio = false

  constructor(
    private readonly context: AudioContext,
    private readonly onState: (state: SpeechPlaybackState) => void,
  ) {
    context.addEventListener("statechange", this.updateState)
  }

  async resume() {
    this.paused = false
    try {
      await this.context.resume()
      this.updateState()
    } catch (error) {
      if (this.stopped) return
      if (error instanceof Error && error.name === "NotAllowedError") this.onState("blocked")
      else throw error
    }
  }

  async pause() {
    this.paused = true
    this.updateState()
    await this.context.suspend()
  }

  append(bytes: Uint8Array) {
    if (this.stopped) return
    let data = bytes
    if (this.pendingByte !== undefined) {
      data = new Uint8Array(bytes.length + 1)
      data[0] = this.pendingByte
      data.set(bytes, 1)
    }
    this.pendingByte = data.length % 2 ? data[data.length - 1] : undefined
    const sampleCount = Math.floor(data.length / 2)
    if (!sampleCount) return
    const buffer = this.context.createBuffer(1, sampleCount, 24000)
    const samples = buffer.getChannelData(0)
    const view = new DataView(data.buffer, data.byteOffset, sampleCount * 2)
    for (let index = 0; index < sampleCount; index += 1) samples[index] = view.getInt16(index * 2, true) / 32768
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.context.destination)
    source.onended = () => {
      source.disconnect()
      this.sources.delete(source)
      this.updateState()
    }
    this.sources.add(source)
    const start = Math.max(this.context.currentTime + 0.025, this.nextStart)
    source.start(start)
    this.nextStart = start + buffer.duration
    this.hasAudio = true
    this.updateState()
  }

  finish() {
    if (this.pendingByte !== undefined || !this.hasAudio) throw new Error("语音流 PCM 数据不完整")
    this.complete = true
    this.updateState()
  }

  stop() {
    this.stopped = true
    this.context.removeEventListener("statechange", this.updateState)
    for (const source of this.sources) {
      source.onended = null
      source.stop()
      source.disconnect()
    }
    this.sources.clear()
  }

  private readonly updateState = () => {
    if (this.stopped) return
    if (this.complete && this.sources.size === 0) this.onState("ended")
    else if (this.paused) this.onState("paused")
    else if (!this.hasAudio) this.onState("preparing")
    else if (this.context.state !== "running") this.onState("blocked")
    else this.onState(this.sources.size ? "playing" : "preparing")
  }
}
