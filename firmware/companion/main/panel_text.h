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
// The German has its own letters, as "Bestätigen" and not "Bestaetigen".
// The fonts of panel_fonts.h hold them, and not much past them: a letter
// outside those fonts is not drawn at all. PanelTextTest holds each text of
// the table to the letters of the fonts.
#pragma once

#include <stdbool.h>

// name, English, German
#define PANEL_TEXTS(X) \
    X(TXT_CANCEL,          "Cancel",                "Abbrechen") \
    X(TXT_CONFIRM,         "Confirm",               "Bestätigen") \
    X(TXT_BACK,            "< Back",                "< Zurück") \
    X(TXT_CONFIRM_SUSPEND, "Suspend the PC?",       "PC in Standby versetzen?") \
    X(TXT_CONFIRM_REBOOT,  "Restart the PC?",       "PC neu starten?") \
    X(TXT_CONFIRM_OFF,     "Switch the PC off?",    "PC ausschalten?") \
    X(TXT_CONFIRM_SETUP,   "Open the setup?",       "Einrichtung öffnen?") \
    X(TXT_SETUP_WHAT,      "Set the network and the PC connection", \
                           "WLAN und PC-Verbindung einrichten") \
    X(TXT_CONFIRM_HERE,    "Confirm on this display.", \
                           "Bitte am Display bestätigen.") \
    X(TXT_SETTINGS_TITLE,  "ESP settings",          "ESP-Einstellungen") \
    X(TXT_BRIGHTNESS,      "Display brightness",    "Displayhelligkeit") \
    X(TXT_BRIGHTNESS_WHAT, "The display of this ESP only", \
                           "Nur das Display dieses ESP") \
    X(TXT_SLEEP_AFTER,     "Display off after",     "Display aus nach") \
    X(TXT_SLEEP_AFTER_WHAT, \
                           "A touch wakes it again, unless the button " \
                           "switched it off", \
                           "Eine Berührung weckt es wieder, außer der " \
                           "Knopf hat es ausgeschaltet") \
    X(TXT_SLEEP_NEVER,     "Never",                 "Nie") \
    X(TXT_LIFT_WAKE,       "Wake when lifted",      "Beim Anheben einschalten") \
    X(TXT_PAGES,           "Pages",                 "Seiten") \
    X(TXT_PAGES_WHAT,      "The top page shown is the start page. The eye hides a page.", \
                           "Die oberste sichtbare ist die Startseite. Das Auge blendet Seiten aus.") \
    X(TXT_PAGES_ARRANGE,   "Arrange",               "Anordnen") \
    X(TXT_PAGES_TITLE,     "Arrange pages",         "Seiten anordnen") \
    X(TXT_PAGES_START,     "Start page",            "Startseite") \
    X(TXT_PAGE_CONTROLS,   "Controls",              "Steuerung") \
    X(TXT_PAGE_SESSION,    "Session and drives",    "Sitzung und Datenträger") \
    X(TXT_PAGE_CLOCK,      "Clock and timer",       "Uhr und Timer") \
    X(TXT_PAGE_CARD,       "Graphics card and history", "Grafikkarte und Verlauf") \
    X(TXT_PAGE_LED,        "LED bar",               "LED-Leiste") \
    X(TXT_PAGE_CPU,        "CPU energy",            "CPU-Energie") \
    X(TXT_LIFT_WAKE_WHAT,  "Only when it went off by itself, not after the button", \
                           "Nur wenn es von selbst ausging, nicht nach dem Knopf") \
    X(TXT_MINUTES,         "min",                   "Min") \
    X(TXT_CONNECTION,      "Connection",            "Verbindung") \
    X(TXT_TONES,           "Key tones",             "Tastentöne") \
    X(TXT_TONES_WHAT,      "A sound at each press on this panel", \
                           "Ton bei Bedienung des Panels") \
    X(TXT_ESP_VOLUME,      "ESP volume",            "ESP-Lautstärke") \
    X(TXT_TEST_TONE,       "Test tone",             "Testton") \
    X(TXT_SPEAKER,         "Local speaker",         "Lokaler Lautsprecher") \
    X(TXT_NO_AUDIO,        "No audio device",       "Audio nicht verfügbar") \
    X(TXT_LANGUAGE,        "Language",              "Sprache") \
    X(TXT_LANGUAGE_WHAT,   "The words on this panel", \
                           "Die Beschriftung dieses Panels") \
    X(TXT_AUTOSAVE,        "Changes save themselves.", \
                           "Änderungen werden automatisch gespeichert.") \
    X(TXT_CONTROLLERS,     "Controllers",           "Controller") \
    X(TXT_NO_PADS,         "No controller connected", \
                           "Kein Controller verbunden") \
    X(TXT_NO_BATTERY,      "No battery reading",    "Kein Akkustand") \
    X(TXT_PC_AUDIO,        "PC AUDIO",              "PC-TON") \
    X(TXT_SELF_TITLE,      "Panel info",            "Panel-Info") \
    X(TXT_SELF_FIRMWARE,   "FIRMWARE",              "FIRMWARE") \
    X(TXT_SELF_VERSION,    "Version",               "Version") \
    X(TXT_SELF_BUILD,      "Build %s (%s)",         "Build %s (%s)") \
    X(TXT_SELF_MEMORY,     "Free memory",           "Freier Speicher") \
    X(TXT_SELF_SIGNAL,     "Signal",                "Signal") \
    X(TXT_SELF_SERVER,     "PC address",            "PC-Adresse") \
    X(TXT_SELF_POWER,      "POWER",                 "STROMVERSORGUNG") \
    X(TXT_SELF_CHARGE,     "Charge",                "Ladestand") \
    X(TXT_SELF_SUPPLY,     "Supply",                "Versorgung") \
    X(TXT_SELF_CABLE,      "Cable",                 "Kabel") \
    X(TXT_SELF_VBAT,       "Battery voltage",       "Akkuspannung") \
    X(TXT_SELF_PHASE,      "Charge phase",          "Ladephase") \
    X(TXT_SELF_VBUS,       "USB voltage",           "USB-Spannung") \
    X(TXT_SELF_VSYS,       "System voltage",        "Systemspannung") \
    X(TXT_SELF_DIE,        "PMU temperature",       "PMU-Temperatur") \
    X(TXT_SELF_HELD,       "Throttled by",          "Gedrosselt durch") \
    X(TXT_SELF_CHARGER,    "CHARGER",               "LADEGERÄT") \
    X(TXT_SELF_MOTION,     "DISPLAY IN MOTION",     "ANZEIGE IN BEWEGUNG") \
    X(TXT_SELF_FPS,        "Frame rate",            "Bildrate") \
    X(TXT_SELF_FPS_SAID,   "%d fps (%u frames)",    "%d fps (%u Bilder)") \
    X(TXT_SELF_INTERVAL,   "Frame interval",        "Bildabstand") \
    X(TXT_SELF_DRAW,       "Draw time",             "Zeichenzeit") \
    X(TXT_SELF_LEAD,       "Lead time",             "Vorlauf") \
    X(TXT_SELF_PERIODS,    "Panel frames",          "Panelbilder") \
    X(TXT_SELF_MOTION_WHAT,"Mean / 95 % / most; panel frames 1 / 2 / 3 / 4+. Since this page was last closed.", \
                           "Mittel / 95 % / Höchstwert; Panelbilder 1 / 2 / 3 / 4+. Seit dem letzten Schließen dieser Seite.") \
    X(TXT_SELF_CHARGE_MA,  "Charge current",        "Ladestrom") \
    X(TXT_SELF_CHARGE_MV,  "Charge voltage",        "Ladeschluss") \
    X(TXT_SELF_INPUT_MA,   "Input limit",           "Eingangsgrenze") \
    X(TXT_PHASE_TRICKLE,   "Trickle",               "Erhaltungsladung") \
    X(TXT_PHASE_PRE,       "Pre-charge",            "Vorladen") \
    X(TXT_PHASE_CC,        "Constant current",      "Konstantstrom") \
    X(TXT_PHASE_CV,        "Constant voltage",      "Konstantspannung") \
    X(TXT_PHASE_DONE,      "Done",                  "Fertig") \
    X(TXT_PHASE_IDLE,      "Not charging",          "Lädt nicht") \
    X(TXT_HELD_NOTHING,    "Nothing",               "Nichts") \
    X(TXT_HELD_HEAT,       "Heat",                  "Hitze") \
    X(TXT_HELD_CURRENT,    "USB current",           "USB-Strom") \
    X(TXT_HELD_VOLTAGE,    "USB voltage",           "USB-Spannung") \
    X(TXT_UPDATE,          "UPDATE",                "UPDATE") \
    X(TXT_UPDATE_OFFERED,  "Available",             "Verfügbar") \
    X(TXT_UPDATE_NOW,      "Update now",            "Jetzt aktualisieren") \
    X(TXT_UPDATE_POWER,    "Below 20 %, connect the cable first.", \
                           "Unter 20 % bitte erst das Kabel anschließen.") \
    X(TXT_UPDATE_RUNNING,  "Updating the panel",    "Panel wird aktualisiert") \
    X(TXT_UPDATE_KEEP_ON,  "Do not switch it off.", "Bitte nicht ausschalten.") \
    X(TXT_UPDATE_RESTART,  "The panel restarts.",   "Das Panel startet neu.") \
    X(TXT_UPDATE_FAILED,   "Update failed: %s",     "Update fehlgeschlagen: %s") \
    X(TXT_UPDATE_NO_ANSWER,"The PC did not send the firmware.", \
                           "Der PC hat die Firmware nicht geschickt.") \
    X(TXT_UPDATE_BROKEN,   "The firmware arrived damaged.", \
                           "Die Firmware kam beschädigt an.") \
    X(TXT_UPDATE_WRITE,    "The panel could not write it.", \
                           "Das Panel konnte sie nicht schreiben.") \
    X(TXT_CONFIRM_UPDATE,  "Update the panel?",     "Panel aktualisieren?") \
    X(TXT_UPDATE_WHAT,     "It restarts afterwards.", \
                           "Es startet danach neu.") \
    X(TXT_CPU_TEMPERATURE, "CPU temperature",       "CPU-Temperatur") \
    X(TXT_GPU_TEMPERATURE, "GPU temperature",       "GPU-Temperatur") \
    X(TXT_SENSOR_AUTO,     "Automatic",             "Automatisch") \
    X(TXT_PC_DETAILS,      "PC details",            "PC-Details") \
    X(TXT_PC_SYSTEM,       "SYSTEM",                "SYSTEM") \
    X(TXT_PC_HARDWARE,     "HARDWARE",              "HARDWARE") \
    X(TXT_PC_NETWORK,      "NETWORK",               "NETZWERK") \
    X(TXT_PC_NAME,         "Name",                  "Gerätename") \
    X(TXT_PC_OS,           "Operating system",      "Betriebssystem") \
    X(TXT_PC_BUILD,        "Build",                 "Build-Nummer") \
    X(TXT_PC_CHANNEL,      "Update channel",        "Update-Kanal") \
    X(TXT_PC_KERNEL,       "Kernel",                "Kernel") \
    X(TXT_PC_UPTIME,       "Uptime",                "Laufzeit") \
    X(TXT_PC_CPU,          "Processor",             "Prozessor") \
    X(TXT_PC_LOAD,         "CPU load",              "CPU-Last") \
    X(TXT_PC_GPU,          "GPU model",             "GPU-Modell") \
    X(TXT_PC_MEMORY,       "Memory",                "Arbeitsspeicher") \
    X(TXT_PC_FAN,          "Fans",                  "Lüfter") \
    X(TXT_PC_GPU_FAN,      "GPU fan",               "GPU-Lüfter") \
    X(TXT_PC_IP,           "IP address",            "IP-Adresse") \
    X(TXT_PC_LINK,         "Connection",            "Verbindung") \
    X(TXT_PC_MAC,          "MAC address",           "MAC-Adresse") \
    X(TXT_PC_ANSWER,       "Response time",         "Antwortzeit") \
    X(TXT_WIRED,           "Ethernet",              "LAN") \
    X(TXT_WIRELESS,        "Wi-Fi",                 "WLAN") \
    X(TXT_UPTIME_DAYS,     "%d d %d h %d min",      "%d T. %d Std. %d Min.") \
    X(TXT_UPTIME_HOURS,    "%d h %d min",           "%d Std. %d Min.") \
    X(TXT_RPM,             "%d rpm",                "%d U/min") \
    X(TXT_PC_VOLUME,       "PC VOLUME",             "PC-LAUTSTÄRKE") \
    X(TXT_PC_CONTROL,      "PC CONTROL",            "PC-STEUERUNG") \
    X(TXT_WAKE,            "Wake",                  "Aufwecken") \
    X(TXT_WAKE_WHAT,       "Send a wake signal over the network", \
                           "Weckruf über das Netzwerk senden") \
    X(TXT_WAKE_SENT,       "Wake signal sent",      "Weckruf gesendet") \
    X(TXT_WAKE_FAILED,     "The wake signal did not go out", \
                           "Weckruf konnte nicht gesendet werden") \
    X(TXT_SUSPEND,         "Suspend",               "Standby") \
    X(TXT_REBOOT,          "Restart",               "Neustart") \
    X(TXT_POWEROFF,        "Power off",             "Ausschalten") \
    X(TXT_SETTINGS,        "Settings",              "Einstellungen") \
    X(TXT_SETUP,           "Set up",                "Einrichten") \
    X(TXT_WIFI_OFFLINE,    "NO WI-FI",              "KEIN WLAN") \
    X(TXT_PC_ONLINE,       "PC CONNECTED",          "PC VERBUNDEN") \
    X(TXT_PC_OFFLINE,      "PC OFFLINE",            "PC OFFLINE") \
    X(TXT_MUTED,           "MUTED",                 "STUMM") \
    X(TXT_ACTIVE,          "ON",                    "AN") \
    X(TXT_CHARGING,        "Charging",              "Lädt") \
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
                           "Passwort: %s\n\n2. Im Browser öffnen:\n" \
                           "http://192.168.4.1\n\n" \
                           "3. Heim-WLAN und PC eintragen.") \
    X(TXT_WAIT,            "One moment.",           "Bitte kurz warten.") \
    X(TXT_SENT,            "Sent",                  "Befehl gesendet") \
    X(TXT_NOT_CONFIRMED,   "Not confirmed",         "Befehl nicht bestätigt") \
    X(TXT_CHECK_TOKEN,     "Check the token",       "Token prüfen") \
    X(TXT_CHECK_SETUP,     "Check the token: Set up", \
                           "Token prüfen: Einrichten") \
    X(TXT_FORM_PLEASE,     "Use the setup form.", \
                           "Bitte das Einrichtungsformular verwenden.") \
    X(TXT_FORM_BAD,        "The network, the PC address or the token is wrong.", \
                           "WLAN-Daten, PC-Adresse oder Token ungültig.") \
    X(TXT_TOKEN_BAD,       "The token has characters that are not allowed.", \
                           "Token enthält ungültige Zeichen.") \
    X(TXT_FORM_SAVED,      "Saved. The panel restarts. Put your phone back " \
                           "on your own network.", \
                           "Gespeichert. Das Panel startet neu. Verbinde " \
                           "dein Handy wieder mit deinem Heim-WLAN.") \
    X(TXT_MODE,            "Session", "Sitzung") \
    X(TXT_MODE_GAME,       "Game Mode", "Spielmodus") \
    X(TXT_MODE_DESKTOP,    "Desktop", "Desktop") \
    X(TXT_TO_GAME,         "To Game Mode", "Zum Spielmodus") \
    X(TXT_TO_DESKTOP,      "To Desktop", "Zum Desktop") \
    X(TXT_CONFIRM_MODE,    "Switch the session?", "Sitzung wechseln?") \
    X(TXT_DRIVES,          "Drives", "Datenträger") \
    X(TXT_NO_DRIVES,       "No drive answered.", \
                           "Kein Datenträger hat geantwortet.") \
    X(TXT_FREE,            "free", "frei") \
    X(TXT_PLAYING,         "Now playing", "Läuft gerade") \
    X(TXT_NOTHING_PLAYING, "No game running", "Es läuft kein Spiel") \
    X(TXT_ACHIEVEMENTS,    "ACHIEVEMENTS",          "ERRUNGENSCHAFTEN") \
    X(TXT_CLOCK_UNSET,     "No time yet",           "Noch keine Uhrzeit") \
    X(TXT_DATE_FORMAT,     "%s, %d %s",             "%s, %d. %s") \
    X(TXT_SUNDAY,          "Sunday",                "Sonntag") \
    X(TXT_MONDAY,          "Monday",                "Montag") \
    X(TXT_TUESDAY,         "Tuesday",               "Dienstag") \
    X(TXT_WEDNESDAY,       "Wednesday",             "Mittwoch") \
    X(TXT_THURSDAY,        "Thursday",              "Donnerstag") \
    X(TXT_FRIDAY,          "Friday",                "Freitag") \
    X(TXT_SATURDAY,        "Saturday",              "Samstag") \
    X(TXT_JANUARY,         "January",               "Januar") \
    X(TXT_FEBRUARY,        "February",              "Februar") \
    X(TXT_MARCH,           "March",                 "März") \
    X(TXT_APRIL,           "April",                 "April") \
    X(TXT_MAY,             "May",                   "Mai") \
    X(TXT_JUNE,            "June",                  "Juni") \
    X(TXT_JULY,            "July",                  "Juli") \
    X(TXT_AUGUST,          "August",                "August") \
    X(TXT_SEPTEMBER,       "September",             "September") \
    X(TXT_OCTOBER,         "October",               "Oktober") \
    X(TXT_NOVEMBER,        "November",              "November") \
    X(TXT_DECEMBER,        "December",              "Dezember") \
    X(TXT_TIMER,           "TIMER",                 "TIMER") \
    X(TXT_START,           "Start",                 "Start") \
    X(TXT_PAUSE,           "Pause",                 "Pause") \
    X(TXT_RESET,           "Reset",                 "Zurücksetzen") \
    X(TXT_TIME_UP,         "Time is up",            "Zeit abgelaufen") \
    X(TXT_STOP,            "Stop",                  "Stopp") \
    X(TXT_GPU_LOAD,        "GPU load",              "GPU-Last") \
    X(TXT_GPU_VRAM,        "VRAM",                  "VRAM") \
    X(TXT_GPU_CLOCK,       "GPU clock",             "GPU-Takt") \
    X(TXT_GPU_BOOST,       "Cooling Boost",         "Lüfter-Boost") \
    X(TXT_HISTORY,         "History",               "Verlauf") \
    X(TXT_HISTORY_EMPTY,   "No readings yet",       "Noch keine Werte") \
    X(TXT_HISTORY_NOW,     "now",                   "jetzt") \
    X(TXT_LED_DESKTOP,     "LED bar on the desktop", "LED-Leiste im Desktop-Modus") \
    X(TXT_LED_GAME,        "LED bar in Game Mode",  "LED-Leiste im Spielmodus") \
    X(TXT_LED_NOW,         "Now",                   "Aktiv") \
    X(TXT_LED_GAME_WHAT,   "Shows when the LED menu of Steam is on Rainbow", \
                           "Wirkt, wenn in Steam Regenbogen gewählt ist") \
    X(TXT_LED_COLOUR_WHAT, "In the desktop colour of the control panel", \
                           "In der Desktop-Farbe aus dem Kontrollpanel") \
    X(TXT_CHANGE_APPLYING,    "Applying ...",          "Wird übernommen ...") \
    X(TXT_LED_NONE,        "No LED bar on this PC", "Keine LED-Leiste an diesem PC") \
    X(TXT_PC_TOO_OLD, "Update the PC to use this page", \
                           "PC aktualisieren, um diese Seite zu nutzen") \
    X(TXT_CHANGE_NO_RULE,     "Not permitted: run install.sh on the PC again", \
                           "Nicht erlaubt: install.sh am PC neu ausführen") \
    X(TXT_CHANGE_BUSY,        "The PC is still busy. Try again.", \
                           "Der PC ist noch beschäftigt. Bitte erneut.") \
    X(TXT_LED_NO_MODULE,   "The LED module is not installed", \
                           "Das LED-Modul ist nicht installiert") \
    X(TXT_CHANGE_REFUSED,     "The PC did not take the change", \
                           "Der PC hat die Änderung nicht übernommen") \
    X(TXT_LED_UNKNOWN,     "--",                    "--") \
    X(TXT_LED_STEAM,       "Leave it to Steam",     "Steam überlassen") \
    X(TXT_LED_OFF,         "Off",                   "Aus") \
    X(TXT_LED_COLOR,       "One colour",            "Eine Farbe") \
    X(TXT_LED_BREATH,      "Breathing",             "Atmen") \
    X(TXT_LED_PATROL,      "Patrol",                "Lauflicht") \
    X(TXT_LED_RAINBOW,     "Rainbow",               "Regenbogen") \
    X(TXT_LED_FIRE,        "Fire",                  "Feuer") \
    X(TXT_LED_AURORA,      "Aurora",                "Polarlicht") \
    X(TXT_LED_OOZE,        "Ooze",                  "Schleim") \
    X(TXT_LED_TEMPERATURE, "Temperature",           "Temperatur") \
    X(TXT_LED_LOAD,        "CPU and GPU load",      "CPU- und GPU-Last") \
    X(TXT_LED_COLOUR,      "Colour",                "Farbe") \
    X(TXT_LED_BRIGHTNESS,  "Brightness",            "Helligkeit") \
    X(TXT_LED_DONE,        "Done",                  "Fertig") \
    X(TXT_COLOUR_RED,      "Red",                   "Rot") \
    X(TXT_COLOUR_ORANGE,   "Orange",                "Orange") \
    X(TXT_COLOUR_YELLOW,   "Yellow",                "Gelb") \
    X(TXT_COLOUR_GREEN,    "Green",                 "Grün") \
    X(TXT_COLOUR_CYAN,     "Cyan",                  "Cyan") \
    X(TXT_COLOUR_BLUE,     "Blue",                  "Blau") \
    X(TXT_COLOUR_PURPLE,   "Purple",                "Lila") \
    X(TXT_COLOUR_MAGENTA,  "Magenta",               "Magenta") \
    X(TXT_COLOUR_WHITE,    "White",                 "Weiß") \
    X(TXT_COLOUR_OWN,      "Own colour",            "Eigene Farbe") \
    X(TXT_CPU_TITLE,       "CPU energy profile",    "CPU-Energieprofil") \
    X(TXT_CPU_POWERSAVE,   "Power saving",          "Sparsam") \
    X(TXT_CPU_BALANCED,    "Balanced",              "Ausgewogen") \
    X(TXT_CPU_PERFORMANCE, "Performance",           "Leistung") \
    X(TXT_CPU_STEAMOS,     "Leave it to SteamOS (from the next start)", \
                           "SteamOS überlassen (ab dem nächsten Start)") \
    X(TXT_CPU_RUNNING,     "Running now",           "Läuft gerade") \
    X(TXT_CPU_DRIVER,      "Driver: %s",            "Treiber: %s") \
    X(TXT_CPU_CUSTOM,      "A setting of the control panel", \
                           "Eigene Einstellung aus dem Kontrollpanel") \
    X(TXT_CPU_NONE,        "No CPU and GPU power module on this PC", \
                           "Kein CPU- und GPU-Modul auf diesem PC") \
    X(TXT_CPU_NO_MODULE,   "The CPU and GPU power module is not installed", \
                           "Das CPU- und GPU-Modul ist nicht installiert")

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
