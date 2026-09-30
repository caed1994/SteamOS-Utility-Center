// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Every word this panel puts on its screen, in each language it offers.
//
// One list and not two tables. A language is a column of PANEL_TEXTS below,
// and the enum, the English table and the German table are all built from
// that one list. So a text that somebody adds to one of them is in all of
// them, and a table with a hole in it cannot be written at all. The hole is
// what matters here: a missing entry is a null pointer that LVGL follows,
// and the panel restarts in front of the person using it.
//
// The German is written without umlauts, as "Bestaetigen" and not
// "Bestätigen". The fonts built into this firmware are a subset, and a
// character outside it draws as an empty box. PanelTextTest holds that rule.
#pragma once

#include <stdbool.h>

// name, English, German
#define PANEL_TEXTS(X) \
    X(TXT_CANCEL,          "Cancel",                "Abbrechen") \
    X(TXT_CONFIRM,         "Confirm",               "Bestaetigen") \
    X(TXT_BACK,            "< Back",                "< Zurueck") \
    X(TXT_CONFIRM_SUSPEND, "Suspend the PC?",       "PC in Standby versetzen?") \
    X(TXT_CONFIRM_REBOOT,  "Restart the PC?",       "PC neu starten?") \
    X(TXT_CONFIRM_OFF,     "Switch the PC off?",    "PC ausschalten?") \
    X(TXT_CONFIRM_SETUP,   "Open the setup?",       "Einrichtung oeffnen?") \
    X(TXT_SETUP_WHAT,      "Set the network and the PC connection", \
                           "WLAN und PC-Verbindung konfigurieren") \
    X(TXT_CONFIRM_HERE,    "Confirm on this display.", \
                           "Bitte am Display bestaetigen.") \
    X(TXT_SETTINGS_TITLE,  "ESP settings",          "ESP-Einstellungen") \
    X(TXT_BRIGHTNESS,      "Display brightness",    "Displayhelligkeit") \
    X(TXT_BRIGHTNESS_WHAT, "The display of this ESP only", \
                           "Nur das Display dieses ESP") \
    X(TXT_SLEEP_AFTER,     "Display off after",     "Display aus nach") \
    X(TXT_SLEEP_AFTER_WHAT, \
                           "A touch wakes it again, unless the button " \
                           "switched it off", \
                           "Beruehrung weckt es wieder, ausser der Knopf " \
                           "hat es ausgeschaltet") \
    X(TXT_SLEEP_NEVER,     "Never",                 "Nie") \
    X(TXT_MINUTES,         "min",                   "Min") \
    X(TXT_CONNECTION,      "Connection",            "Verbindung") \
    X(TXT_TONES,           "Key tones",             "Tastentoene") \
    X(TXT_TONES_WHAT,      "A sound at each press on this panel", \
                           "Ton bei Bedienung des Panels") \
    X(TXT_ESP_VOLUME,      "ESP volume",            "ESP-Lautstaerke") \
    X(TXT_TEST_TONE,       "Test tone",             "Testton") \
    X(TXT_SPEAKER,         "Local speaker",         "Lokaler Lautsprecher") \
    X(TXT_NO_AUDIO,        "No audio device",       "Audio nicht verfuegbar") \
    X(TXT_LANGUAGE,        "Language",              "Sprache") \
    X(TXT_LANGUAGE_WHAT,   "The words on this panel", \
                           "Die Beschriftung dieses Panels") \
    X(TXT_AUTOSAVE,        "Changes save themselves.", \
                           "Aenderungen werden automatisch gespeichert.") \
    X(TXT_CONTROLLER,      "CONTROLLER",            "CONTROLLER") \
    X(TXT_PC_AUDIO,        "PC AUDIO",              "PC-TON") \
    X(TXT_PC_VOLUME,       "PC VOLUME",             "PC-LAUTSTAERKE") \
    X(TXT_PC_CONTROL,      "PC CONTROL",            "PC-STEUERUNG") \
    X(TXT_WAKE,            "Wake",                  "Aufwecken") \
    X(TXT_WAKE_WHAT,       "Send a wake signal over the network", \
                           "Weckruf ueber das Netzwerk senden") \
    X(TXT_WAKE_SENT,       "Wake signal sent",      "Weckruf gesendet") \
    X(TXT_WAKE_FAILED,     "The wake signal did not go out", \
                           "Weckruf konnte nicht gesendet werden") \
    X(TXT_SUSPEND,         "Suspend",               "Standby") \
    X(TXT_REBOOT,          "Restart",               "Neustart") \
    X(TXT_POWEROFF,        "Power off",             "Ausschalten") \
    X(TXT_SETTINGS,        "Settings",              "Einstellungen") \
    X(TXT_SETUP,           "Set up",                "Einrichten") \
    X(TXT_WIFI_OFFLINE,    "NO WI-FI",              "WLAN OFFLINE") \
    X(TXT_PC_ONLINE,       "PC CONNECTED",          "PC VERBUNDEN") \
    X(TXT_PC_OFFLINE,      "PC OFFLINE",            "PC OFFLINE") \
    X(TXT_MUTED,           "MUTED",                 "STUMM") \
    X(TXT_ACTIVE,          "ON",                    "AKTIV") \
    X(TXT_CHARGING,        "Charging",              "Wird geladen") \
    X(TXT_CHARGED,         "Fully charged",         "Voll geladen") \
    X(TXT_ON_BATTERY,      "On battery",            "Akkubetrieb") \
    X(TXT_ATTACHED,        "Connected",             "Verbunden") \
    X(TXT_SETUP_TITLE,     "Set up the panel",      "Panel einrichten") \
    X(TXT_SETUP_STOP,      "Restart the panel to stop.", \
                           "Zum Abbrechen das Panel neu starten.") \
    X(TXT_SETUP_STEPS,     "1. Join this network:\n%s\n\nPassword: %s\n\n" \
                           "2. Open in a browser:\nhttp://192.168.4.1\n\n" \
                           "3. Give it your network and your PC.", \
                           "1. Mit diesem WLAN verbinden:\n%s\n\n" \
                           "Passwort: %s\n\n2. Im Browser oeffnen:\n" \
                           "http://192.168.4.1\n\n" \
                           "3. Heim-WLAN und PC eintragen.") \
    X(TXT_WAIT,            "One moment.",           "Bitte kurz warten.") \
    X(TXT_SENT,            "Sent",                  "Befehl gesendet") \
    X(TXT_NOT_CONFIRMED,   "Not confirmed",         "Befehl nicht bestaetigt") \
    X(TXT_CHECK_TOKEN,     "Check the token",       "Token pruefen") \
    X(TXT_CHECK_SETUP,     "Check the token: Set up", \
                           "Token pruefen: Einrichten") \
    X(TXT_FORM_PLEASE,     "Use the setup form.", \
                           "Bitte das Einrichtungsformular verwenden.") \
    X(TXT_FORM_BAD,        "The network, the PC address or the token is wrong.", \
                           "WLAN-Daten, PC-Adresse oder Token ungueltig.") \
    X(TXT_TOKEN_BAD,       "The token has characters that are not allowed.", \
                           "Token enthaelt ungueltige Zeichen.") \
    X(TXT_FORM_SAVED,      "Saved. The panel restarts. Put your phone back " \
                           "on your own network.", \
                           "Gespeichert. Das Panel startet neu. Verbinde " \
                           "dein Handy wieder mit deinem Heim-WLAN.") \
    X(TXT_MODE,            "Session", "Sitzung") \
    X(TXT_MODE_GAME,       "Game Mode", "Game Mode") \
    X(TXT_MODE_DESKTOP,    "Desktop", "Desktop") \
    X(TXT_TO_GAME,         "To Game Mode", "Zu Game Mode") \
    X(TXT_TO_DESKTOP,      "To Desktop", "Zum Desktop") \
    X(TXT_CONFIRM_MODE,    "Switch the session?", "Sitzung wechseln?") \
    X(TXT_DRIVES,          "Drives", "Datentraeger") \
    X(TXT_NO_DRIVES,       "No drive answered.", \
                           "Kein Datentraeger hat geantwortet.") \
    X(TXT_FREE,            "free", "frei") \
    X(TXT_PLAYING,         "Now playing", "Laeuft gerade") \
    X(TXT_NOTHING_PLAYING, "No game running", "Es laeuft kein Spiel") \
    X(TXT_ACHIEVEMENTS,    "ACHIEVEMENTS",          "ERRUNGENSCHAFTEN")

typedef enum {
#define PANEL_TEXT_AS_ENUM(name, english, german) name,
    PANEL_TEXTS(PANEL_TEXT_AS_ENUM)
#undef PANEL_TEXT_AS_ENUM
    TXT_COUNT
} panel_text_id_t;

// English leads, so a panel with nothing stored answers in it.
typedef enum {
    PANEL_ENGLISH, PANEL_GERMAN, PANEL_LANGUAGE_COUNT
} panel_language_t;

const char *panel_text(panel_text_id_t id);
void panel_text_set(panel_language_t language);
panel_language_t panel_text_language(void);

// The name of a language, in that language. A person who cannot read the
// current one still finds their own in the list.
const char *panel_language_name(panel_language_t language);
