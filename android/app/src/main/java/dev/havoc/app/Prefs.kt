package dev.havoc.app

import android.content.Context
import android.webkit.CookieManager

/** Phone-side settings. The brain (and every secret) lives on the PC; this only knows where it is. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("havoc", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit().putString("server", v.trimEnd('/')).apply()

    var session: String
        get() = sp.getString("session", "") ?: ""
        set(v) = sp.edit().putString("session", v).apply()

    var wakeEnabled: Boolean
        get() = sp.getBoolean("wake", false)
        set(v) = sp.edit().putBoolean("wake", v).apply()

    var onlyWhileCharging: Boolean
        get() = sp.getBoolean("charging", false)
        set(v) = sp.edit().putBoolean("charging", v).apply()

    val configured: Boolean get() = serverUrl.isNotBlank()

    /** Session cookie for native calls: the WebView's copy wins (it refreshes on login). */
    fun cookieHeader(): String {
        val fromWebView = runCatching { CookieManager.getInstance().getCookie(serverUrl) }.getOrNull()
        if (!fromWebView.isNullOrBlank() && fromWebView.contains(COOKIE)) return fromWebView
        return if (session.isNotBlank()) "$COOKIE=$session" else ""
    }

    companion object {
        const val COOKIE = "havoc_session"
    }
}
