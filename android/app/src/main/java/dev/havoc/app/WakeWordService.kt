package dev.havoc.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.media.ToneGenerator
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONObject
import org.vosk.LibVosk
import org.vosk.LogLevel
import org.vosk.Model
import org.vosk.Recognizer
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread
import kotlin.math.sqrt

/**
 * "Hey Havoc", entirely on the phone: Vosk keyword spotting with a two-phrase grammar, then a
 * short recording sent to the PC as a voice turn. It never registers as an assistant, so Google
 * Assistant and "Hey Google" are untouched.
 *
 * Actions: START (keep listening), LISTEN (take one command now, from the tile/shortcut), STOP.
 */
class WakeWordService : Service() {
    private lateinit var prefs: Prefs
    @Volatile private var running = false
    @Volatile private var busy = false
    @Volatile private var listenNow = false
    private var worker: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var player: MediaPlayer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_LISTEN, "Listening", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Shown while HAVOC listens for \"Hey Havoc\""
        })
        nm.createNotificationChannel(NotificationChannel(CH_REPLY, "Replies", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "HAVOC's answers to voice commands"
        })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                prefs.wakeEnabled = false
                shutdown()
                return START_NOT_STICKY
            }
            ACTION_LISTEN -> listenNow = true
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        goForeground(if (listenNow && !prefs.wakeEnabled) "Listening..." else "Listening for \"Hey Havoc\"")
        if (!running) {
            running = true
            worker = thread(name = "havoc-wake") { runLoop() }
        }
        return if (prefs.wakeEnabled) START_STICKY else START_NOT_STICKY
    }

    private fun goForeground(text: String) {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, WakeWordService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CH_LISTEN)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle("HAVOC")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build())
            .build()
        if (Build.VERSION.SDK_INT >= 30) startForeground(NOTE_LISTEN, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(NOTE_LISTEN, n)
    }

    // ------------------------------------------------------------------ audio loop
    @SuppressLint("MissingPermission")
    private fun runLoop() {
        acquireWakeLock()
        val model = try {
            loadModel()
        } catch (e: Exception) {
            notifyReply("Couldn't set up \"Hey Havoc\"", e.message ?: "Model download failed. Check your connection and try again.")
            shutdown()
            return
        }
        LibVosk.setLogLevel(LogLevel.WARNINGS)
        val recognizer = Recognizer(model, RATE.toFloat(), "[\"hey havoc\", \"havoc\", \"[unk]\"]")
        val minBuf = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        var rec: AudioRecord? = null
        val buf = ByteArray(CHUNK)
        var noise = 300.0
        try {
            while (running) {
                val shouldListen = listenNow || (prefs.wakeEnabled && (!prefs.onlyWhileCharging || isCharging()))
                if (!shouldListen) {
                    rec?.stop(); rec?.release(); rec = null
                    if (!prefs.wakeEnabled && !busy) break // one-shot finished
                    Thread.sleep(3000)
                    continue
                }
                if (rec == null) {
                    rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, CHUNK * 4))
                    if (rec.state != AudioRecord.STATE_INITIALIZED) {
                        rec.release(); rec = null
                        Thread.sleep(2000) // mic busy (a call, another app): try again shortly
                        continue
                    }
                    rec.startRecording()
                }
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) { Thread.sleep(50); continue }
                if (busy) continue // waiting on the PC or playing a reply: don't listen to ourselves
                val level = rms(buf, n)

                var heard = false
                if (listenNow) {
                    heard = true
                } else {
                    val text = if (recognizer.acceptWaveForm(buf, n)) JSONObject(recognizer.result).optString("text")
                    else JSONObject(recognizer.partialResult).optString("partial")
                    if (text.contains("hey havoc")) heard = true
                    else if (level < noise * 2) noise = noise * 0.95 + level * 0.05 // track room noise
                }
                if (heard) {
                    listenNow = false
                    recognizer.reset()
                    chime()
                    val pcm = captureCommand(rec, noise)
                    if (pcm == null) {
                        notifyReply("HAVOC", "Didn't catch that, Sir.")
                    } else {
                        busy = true
                        thread(name = "havoc-turn") { sendTurn(pcm) }
                    }
                }
            }
        } finally {
            rec?.stop(); rec?.release()
            recognizer.close()
            model.close()
            releaseWakeLock()
            if (!prefs.wakeEnabled) stopSelfSafely()
        }
    }

    /** Records until ~0.9 s of silence after speech (max 15 s). Null if nothing was said within 6 s. */
    private fun captureCommand(rec: AudioRecord, noise: Double): ByteArray? {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(CHUNK)
        val threshold = maxOf(noise * 3, 600.0)
        val chunkMs = CHUNK / 2 * 1000 / RATE
        var spoken = false
        var quietMs = 0
        var waitedMs = 0
        while (running && out.size() < RATE * 2 * 15) {
            val n = rec.read(buf, 0, buf.size)
            if (n <= 0) continue
            val loud = rms(buf, n) > threshold
            if (!spoken) {
                waitedMs += chunkMs
                if (loud) spoken = true else if (waitedMs > 6000) return null
            }
            out.write(buf, 0, n)
            if (spoken) {
                quietMs = if (loud) 0 else quietMs + chunkMs
                if (quietMs >= 900) break
            }
        }
        return if (spoken) out.toByteArray() else null
    }

    private fun sendTurn(pcm: ByteArray) {
        try {
            val reply = HavocApi.voice(prefs.serverUrl, prefs.cookieHeader(), HavocApi.wav(pcm, RATE))
            notifyReply(if (reply.transcript.isNotBlank()) "“${reply.transcript}”" else "HAVOC", reply.reply)
            if (reply.audioUrl != null) play(reply.audioUrl) else busy = false
        } catch (e: Exception) {
            notifyReply("HAVOC couldn't reach your PC", e.message ?: "Is Tailscale on and HAVOC running?")
            busy = false
        }
    }

    private fun play(url: String) {
        runCatching {
            player?.release()
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                setDataSource(this@WakeWordService, Uri.parse(url), mapOf("Cookie" to prefs.cookieHeader()))
                setOnCompletionListener { busy = false; it.release(); player = null }
                setOnErrorListener { mp, _, _ -> busy = false; mp.release(); player = null; true }
                prepare()
                start()
            }
        }.onFailure { busy = false }
    }

    // ------------------------------------------------------------------ model
    private fun loadModel(): Model {
        val dir = File(filesDir, MODEL_NAME)
        if (!File(dir, "am").exists()) {
            goForeground("Downloading the \"Hey Havoc\" model (40 MB, once)...")
            val tmp = File(cacheDir, "model.zip")
            val conn = URL(MODEL_URL).openConnection() as HttpURLConnection
            conn.connectTimeout = 15_000
            conn.readTimeout = 60_000
            conn.inputStream.use { input -> tmp.outputStream().use { input.copyTo(it) } }
            ZipInputStream(tmp.inputStream()).use { zip ->
                var entry = zip.nextEntry
                while (entry != null) {
                    val target = File(filesDir, entry.name).canonicalFile
                    require(target.path.startsWith(filesDir.canonicalPath)) { "bad zip entry" }
                    if (entry.isDirectory) target.mkdirs() else { target.parentFile?.mkdirs(); target.outputStream().use { zip.copyTo(it) } }
                    entry = zip.nextEntry
                }
            }
            tmp.delete()
            goForeground("Listening for \"Hey Havoc\"")
        }
        return Model(dir.absolutePath)
    }

    // ------------------------------------------------------------------ helpers
    private fun rms(buf: ByteArray, n: Int): Double {
        var sum = 0.0
        var i = 0
        while (i + 1 < n) {
            val s = (buf[i].toInt() and 0xFF) or (buf[i + 1].toInt() shl 8)
            sum += (s.toShort().toDouble()).let { it * it }
            i += 2
        }
        return sqrt(sum / maxOf(1, n / 2))
    }

    private fun chime() = runCatching {
        ToneGenerator(AudioManager.STREAM_NOTIFICATION, 60).apply { startTone(ToneGenerator.TONE_PROP_BEEP2, 160) }
        Thread.sleep(200)
    }

    private fun isCharging(): Boolean {
        val status = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))?.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
    }

    private fun notifyReply(title: String, text: String) {
        val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CH_REPLY)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { getSystemService(NotificationManager::class.java).notify(NOTE_REPLY, n) }
    }

    private fun acquireWakeLock() {
        wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "havoc:wake").apply { setReferenceCounted(false); acquire() }
    }

    private fun releaseWakeLock() = runCatching { wakeLock?.release() }

    private fun shutdown() {
        running = false
        player?.release(); player = null
        stopSelfSafely()
    }

    private fun stopSelfSafely() {
        if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "dev.havoc.app.START"
        const val ACTION_LISTEN = "dev.havoc.app.LISTEN"
        const val ACTION_STOP = "dev.havoc.app.STOP"
        private const val CH_LISTEN = "listen"
        private const val CH_REPLY = "reply"
        private const val NOTE_LISTEN = 1
        private const val NOTE_REPLY = 2
        private const val RATE = 16_000
        private const val CHUNK = 4096 // 128 ms of 16-bit mono
        private const val MODEL_NAME = "vosk-model-small-en-us-0.15"
        private const val MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, WakeWordService::class.java).setAction(ACTION_START))
        fun listenOnce(ctx: Context) = ctx.startForegroundService(Intent(ctx, WakeWordService::class.java).setAction(ACTION_LISTEN))
        fun stop(ctx: Context) { ctx.startService(Intent(ctx, WakeWordService::class.java).setAction(ACTION_STOP)) }
    }
}
