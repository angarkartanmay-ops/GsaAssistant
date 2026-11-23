package dev.havoc.app

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.util.TypedValue
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import kotlin.concurrent.thread

/** First run + phone settings: where the PC is, the PIN, and "Hey Havoc". Built in code, no XML. */
class SetupActivity : Activity() {
    private lateinit var prefs: Prefs
    private var urlField: EditText? = null
    private val ink = 0xFF0C0D10.toInt()
    private val panel = 0xFF121419.toInt()
    private val fog = 0xFFE8EAEF.toInt()
    private val muted = 0xFF8A909C.toInt()
    private val signal = 0xFF5CB4D9.toInt()
    private val bad = 0xFFE06A70.toInt()

    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

    private fun label(text: String, size: Float = 14f, color: Int = muted, bold: Boolean = false) = TextView(this).apply {
        this.text = text
        setTextColor(color)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        if (bold) typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }

    private fun field(hint: String, value: String, type: Int) = EditText(this).apply {
        this.hint = hint
        setText(value)
        inputType = type
        setTextColor(fog)
        setHintTextColor(0xFF6B717D.toInt())
        setPadding(dp(14), dp(12), dp(14), dp(12))
        background = GradientDrawable().apply { setColor(panel); cornerRadius = dp(12).toFloat(); setStroke(dp(1), 0x14FFFFFF) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(48), dp(24), dp(32))
        }
        val gap = { h: Int -> col.addView(android.view.View(this), LinearLayout.LayoutParams(MATCH_PARENT, dp(h))) }

        col.addView(label("H.A.V.O.C.", 16f, fog, bold = true).apply { letterSpacing = 0.3f; typeface = Typeface.MONOSPACE })
        gap(6)
        col.addView(label("Connect this phone to the HAVOC running on your PC. Your accounts and keys stay on the PC; this phone only gets a session.", 14f))
        gap(24)

        col.addView(label("PC address (from Connections > Phone)"))
        gap(6)
        val url = field("https://my-pc.tail1234.ts.net", prefs.serverUrl, InputType.TYPE_TEXT_VARIATION_URI)
        urlField = url
        col.addView(url)
        gap(14)
        col.addView(label("PIN"))
        gap(6)
        val pin = field("PIN", "", InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD)
        col.addView(pin)
        gap(8)
        val status = label("", 13f)
        col.addView(status)
        gap(10)
        val connect = Button(this).apply {
            text = if (prefs.configured) "Reconnect" else "Connect"
            setTextColor(ink)
            isAllCaps = false
            background = GradientDrawable().apply { setColor(signal); cornerRadius = dp(12).toFloat() }
        }
        col.addView(connect, LinearLayout.LayoutParams(MATCH_PARENT, dp(50)))

        gap(32)
        col.addView(label("Hey Havoc", 16f, fog, bold = true))
        gap(4)
        col.addView(label("Listens on this phone for \"Hey Havoc\", offline. It's a separate app: Google Assistant and \"Hey Google\" keep working exactly as before. Uses a little battery while on.", 13f))
        gap(10)
        val wake = Switch(this).apply { text = "Listen for \"Hey Havoc\""; setTextColor(fog); isChecked = prefs.wakeEnabled }
        col.addView(wake)
        val charging = Switch(this).apply { text = "Only while charging"; setTextColor(fog); isChecked = prefs.onlyWhileCharging }
        col.addView(charging)

        setContentView(ScrollView(this).apply { setBackgroundColor(ink); addView(col, MATCH_PARENT, WRAP_CONTENT) })

        connect.setOnClickListener {
            val server = url.text.toString().trim().trimEnd('/').let { if (it.startsWith("http")) it else "https://$it" }
            val code = pin.text.toString().trim()
            if (code.length < 4) { status.setTextColor(bad); status.text = "Enter your PIN."; return@setOnClickListener }
            status.setTextColor(muted); status.text = "Connecting..."
            connect.isEnabled = false
            thread {
                val result = runCatching { HavocApi.login(server, code) }
                runOnUiThread {
                    connect.isEnabled = true
                    result.onSuccess { token ->
                        prefs.serverUrl = server
                        prefs.session = token
                        CookieManager.getInstance().setCookie(server, "${Prefs.COOKIE}=$token; Path=/")
                        CookieManager.getInstance().flush()
                        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
                        finish()
                    }.onFailure { e ->
                        status.setTextColor(bad)
                        status.text = (e.message ?: "Couldn't reach the PC.") +
                            if (e !is HavocApi.ApiException) " Is Tailscale on, and is HAVOC running on the PC?" else ""
                    }
                }
            }
        }
        wake.setOnCheckedChangeListener { _, on ->
            if (on && !permissionsOk()) {
                wake.isChecked = false
                return@setOnCheckedChangeListener
            }
            prefs.wakeEnabled = on
            if (on) WakeWordService.start(this) else WakeWordService.stop(this)
        }
        charging.setOnCheckedChangeListener { _, on ->
            prefs.onlyWhileCharging = on
            if (prefs.wakeEnabled) WakeWordService.start(this) // re-reads the setting
        }
    }

    /** The download page has a "Copy address" button; pick that address up so nothing needs typing.
     *  (Android only lets the focused app read the clipboard, hence here and not in onCreate.) */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        val field = urlField ?: return
        if (!hasFocus || field.text.isNotBlank()) return
        val clip = runCatching {
            (getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager).primaryClip
                ?.getItemAt(0)?.coerceToText(this)?.toString()?.trim()
        }.getOrNull() ?: return
        if (Regex("^https://[a-z0-9-]+(\\.[a-z0-9-]+)*\\.ts\\.net/?$").matches(clip)) field.setText(clip.trimEnd('/'))
    }

    private fun permissionsOk(): Boolean {
        val needed = buildList {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (needed.isEmpty()) return true
        requestPermissions(needed.toTypedArray(), 21)
        return false
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            prefs.wakeEnabled = true
            WakeWordService.start(this)
            recreate()
        }
    }
}
