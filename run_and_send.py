import os
import subprocess

from telegram import send_telegram


def main():

    env = os.environ.copy()

    result = subprocess.run(
        ["python3", "scanner.py"],
        capture_output=True,
        text=True,
        env=env
    )

    output = result.stdout

    print(output)

    marker = "🔥 ΣΗΜΕΡΙΝΑ ΣΗΜΕΙΑ"

    if marker not in output:
        print("❌ Δεν βρέθηκε τελικό αποτέλεσμα.")
        return

    section = output.split(marker, 1)[1].strip()

    # Αν δεν υπάρχει επιλογή, δεν στέλνουμε μήνυμα.
    if "❌ Σήμερα δεν βρέθηκε σημείο" in section:
        print("ℹ️ Δεν υπάρχει PLAY. Δεν στέλνω Telegram.")
        return

    # Κρατάμε μόνο το τελικό section.
    message = (
        "🔥 ΣΗΜΕΡΙΝΑ ΣΗΜΕΙΑ\n\n"
        + section
    )

    if send_telegram(message):
        print("✅ Τα σημεία στάλθηκαν στο Telegram.")
    else:
        print("❌ Αποτυχία αποστολής Telegram.")


if __name__ == "__main__":
    main()
