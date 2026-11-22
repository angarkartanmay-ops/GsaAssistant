package dev.havoc.app

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle

/**
 * Invisible trampoline for the "Talk to Havoc" home-screen shortcut and Quick Settings tile.
 * Starting the microphone from a visible activity keeps Android 14+'s background-mic rules happy.
 */
class TalkActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)
        when {
            !prefs.configured -> startActivity(Intent(this, SetupActivity::class.java))
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ->
                startActivity(Intent(this, MainActivity::class.java)) // the app asks for the mic there
            else -> WakeWordService.listenOnce(this)
        }
        finish()
    }
}
