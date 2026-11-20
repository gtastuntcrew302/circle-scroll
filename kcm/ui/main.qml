import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    Kirigami.FormLayout {
        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Circle scrolling:")
            text: i18n("Enable")
            checked: kcm.circleEnabled
            onToggled: kcm.circleEnabled = checked
        }

        QQC2.Label {
            text: i18n("Put one finger on the outer edge of the touchpad and run it around the circle to scroll, like an iPod wheel.")
            wrapMode: Text.WordWrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            opacity: 0.7
        }

        Item {
            Kirigami.FormData.isSection: true
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Scroll speed:")
            enabled: kcm.circleEnabled
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: i18nc("scroll speed", "Slower")
            }
            QQC2.Slider {
                // Slider position = 40 - degrees per step, so right = faster.
                from: 0
                to: 34
                stepSize: 1
                value: 40 - kcm.degreesPerNotch
                onMoved: kcm.degreesPerNotch = 40 - value
                Layout.preferredWidth: Kirigami.Units.gridUnit * 12
            }
            QQC2.Label {
                text: i18nc("scroll speed", "Faster")
            }
        }

        QQC2.Label {
            enabled: kcm.circleEnabled
            text: i18n("%1° of circling = one scroll step", kcm.degreesPerNotch)
            opacity: 0.7
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Direction:")
            enabled: kcm.circleEnabled
            text: i18n("Clockwise scrolls down")
            checked: kcm.clockwiseScrollsDown
            onToggled: kcm.clockwiseScrollsDown = checked
        }

        QQC2.CheckBox {
            Kirigami.FormData.label: i18n("Smoothness:")
            enabled: kcm.circleEnabled
            text: i18n("Smooth scrolling (like two-finger scrolling)")
            checked: kcm.smoothScrolling
            onToggled: kcm.smoothScrolling = checked
        }

        Item {
            Kirigami.FormData.isSection: true
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            visible: true
            type: kcm.serviceRunning ? Kirigami.MessageType.Positive : Kirigami.MessageType.Warning
            text: kcm.statusText
        }
    }
}
