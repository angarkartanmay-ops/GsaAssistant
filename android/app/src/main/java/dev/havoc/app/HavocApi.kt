package dev.havoc.app

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Tiny HTTP client for the PC: PIN login and voice turns. No third-party libraries. */
object HavocApi {
    class ApiException(message: String) : Exception(message)

    data class VoiceReply(val transcript: String, val reply: String, val audioUrl: String?)

    /** Logs in with the PIN and returns the session token (the value of havoc_session). */
    fun login(server: String, pin: String): String {
        val conn = (URL("$server/login").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            instanceFollowRedirects = false
            connectTimeout = 10_000
            readTimeout = 15_000
            doOutput = true
            setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
        }
        try {
            conn.outputStream.use { it.write("pin=${URLEncoder.encode(pin, "UTF-8")}".toByteArray()) }
            when (conn.responseCode) {
                303, 302, 200 -> Unit
                401 -> throw ApiException("Wrong PIN.")
                429 -> throw ApiException("Too many tries. Wait 15 minutes.")
                403 -> throw ApiException("The PC refused this address. Check the Tailscale name in Connections.")
                else -> throw ApiException("The PC answered ${conn.responseCode}.")
            }
            val cookies = conn.headerFields.entries.filter { it.key.equals("Set-Cookie", true) }.flatMap { it.value }
            val token = cookies.firstNotNullOfOrNull { c ->
                c.split(";").first().trim().takeIf { it.startsWith("${Prefs.COOKIE}=") }?.substringAfter("=")
            }
            return token ?: throw ApiException("Logged in, but the PC sent no session.")
        } finally {
            conn.disconnect()
        }
    }

    /** Sends a recorded WAV to the PC; the PC transcribes, runs the turn, and returns a spoken reply. */
    fun voice(server: String, cookie: String, wav: ByteArray): VoiceReply {
        val boundary = "----havoc${System.currentTimeMillis()}"
        val body = ByteArrayOutputStream()
        DataOutputStream(body).apply {
            writeBytes("--$boundary\r\nContent-Disposition: form-data; name=\"attachments\"\r\n\r\n[]\r\n")
            writeBytes("--$boundary\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n")
            writeBytes("Content-Type: audio/wav\r\n\r\n")
            write(wav)
            writeBytes("\r\n--$boundary--\r\n")
            flush()
        }
        val conn = (URL("$server/api/voice").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10_000
            readTimeout = 240_000 // the PC may be thinking for a while
            doOutput = true
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setRequestProperty("Cookie", cookie)
        }
        try {
            conn.outputStream.use { it.write(body.toByteArray()) }
            val code = conn.responseCode
            if (code == 401) throw ApiException("Session expired. Open HAVOC and enter your PIN.")
            val text = (if (code < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.readText().orEmpty()
            if (code >= 400) throw ApiException(runCatching { JSONObject(text).getString("error") }.getOrDefault("PC error $code"))
            val json = JSONObject(text)
            return VoiceReply(
                transcript = json.optString("transcript"),
                reply = json.optString("reply"),
                audioUrl = json.optString("audio_url").takeIf { it.isNotBlank() && it != "null" }?.let { server + it },
            )
        } finally {
            conn.disconnect()
        }
    }

    /** Wraps 16-bit mono PCM in a WAV header. */
    fun wav(pcm: ByteArray, sampleRate: Int = 16_000): ByteArray {
        val out = ByteArrayOutputStream(pcm.size + 44)
        fun le32(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte(), (v shr 16).toByte(), (v shr 24).toByte()))
        fun le16(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte()))
        out.write("RIFF".toByteArray()); le32(36 + pcm.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); le32(16); le16(1); le16(1); le32(sampleRate); le32(sampleRate * 2); le16(2); le16(16)
        out.write("data".toByteArray()); le32(pcm.size); out.write(pcm)
        return out.toByteArray()
    }
}
