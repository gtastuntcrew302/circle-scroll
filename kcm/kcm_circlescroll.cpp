// System Settings page for circle-scroll.
//
// It only reads and writes ~/.config/circlescrollrc.  The circle-scroll
// service (running as root) checks that file about once a second and applies
// the changes, so no password is needed to switch it on or off.

#include <KConfigGroup>
#include <KLocalizedString>
#include <KPluginFactory>
#include <KQuickConfigModule>
#include <KSharedConfig>

#include <QFile>
#include <QTimer>

namespace
{
constexpr bool DefaultEnabled = true;
constexpr int DefaultDegrees = 20;
constexpr bool DefaultClockwiseDown = true;
constexpr bool DefaultSmooth = true;
const QString StatusPath = QStringLiteral("/run/circle-scroll/status");
}

class CircleScrollKcm : public KQuickConfigModule
{
    Q_OBJECT
    Q_PROPERTY(bool circleEnabled READ circleEnabled WRITE setCircleEnabled NOTIFY settingsChanged)
    Q_PROPERTY(int degreesPerNotch READ degreesPerNotch WRITE setDegreesPerNotch NOTIFY settingsChanged)
    Q_PROPERTY(bool clockwiseScrollsDown READ clockwiseScrollsDown WRITE setClockwiseScrollsDown NOTIFY settingsChanged)
    Q_PROPERTY(bool smoothScrolling READ smoothScrolling WRITE setSmoothScrolling NOTIFY settingsChanged)
    Q_PROPERTY(QString statusText READ statusText NOTIFY statusChanged)
    Q_PROPERTY(bool serviceRunning READ serviceRunning NOTIFY statusChanged)

public:
    CircleScrollKcm(QObject *parent, const KPluginMetaData &data)
        : KQuickConfigModule(parent, data)
        , m_config(KSharedConfig::openConfig(QStringLiteral("circlescrollrc")))
    {
        setButtons(Apply | Default);
        m_statusTimer.setInterval(1500);
        connect(&m_statusTimer, &QTimer::timeout, this, &CircleScrollKcm::refreshStatus);
        m_statusTimer.start();
        refreshStatus();
    }

    bool circleEnabled() const { return m_enabled; }
    int degreesPerNotch() const { return m_degrees; }
    bool clockwiseScrollsDown() const { return m_clockwiseDown; }
    bool smoothScrolling() const { return m_smooth; }
    QString statusText() const { return m_statusText; }
    bool serviceRunning() const { return m_serviceRunning; }

    void setCircleEnabled(bool v) { if (v != m_enabled) { m_enabled = v; changed(); } }
    void setDegreesPerNotch(int v) { v = qBound(4, v, 90); if (v != m_degrees) { m_degrees = v; changed(); } }
    void setClockwiseScrollsDown(bool v) { if (v != m_clockwiseDown) { m_clockwiseDown = v; changed(); } }
    void setSmoothScrolling(bool v) { if (v != m_smooth) { m_smooth = v; changed(); } }

    void load() override
    {
        KQuickConfigModule::load();
        m_config->reparseConfiguration();
        KConfigGroup g(m_config, QStringLiteral("General"));
        m_enabled = g.readEntry("Enabled", DefaultEnabled);
        m_degrees = qBound(4, g.readEntry("DegreesPerNotch", DefaultDegrees), 90);
        m_clockwiseDown = g.readEntry("ClockwiseScrollsDown", DefaultClockwiseDown);
        m_smooth = g.readEntry("SmoothScrolling", DefaultSmooth);
        m_saved = current();
        Q_EMIT settingsChanged();
        updateState();
    }

    void save() override
    {
        KQuickConfigModule::save();
        KConfigGroup g(m_config, QStringLiteral("General"));
        g.writeEntry("Enabled", m_enabled);
        g.writeEntry("DegreesPerNotch", m_degrees);
        g.writeEntry("ClockwiseScrollsDown", m_clockwiseDown);
        g.writeEntry("SmoothScrolling", m_smooth);
        m_config->sync();
        m_saved = current();
        updateState();
    }

    void defaults() override
    {
        KQuickConfigModule::defaults();
        m_enabled = DefaultEnabled;
        m_degrees = DefaultDegrees;
        m_clockwiseDown = DefaultClockwiseDown;
        m_smooth = DefaultSmooth;
        Q_EMIT settingsChanged();
        updateState();
    }

Q_SIGNALS:
    void settingsChanged();
    void statusChanged();

private:
    struct Values {
        bool enabled;
        int degrees;
        bool clockwiseDown;
        bool smooth;
        bool operator==(const Values &o) const = default;
    };

    Values current() const { return {m_enabled, m_degrees, m_clockwiseDown, m_smooth}; }

    void changed()
    {
        Q_EMIT settingsChanged();
        updateState();
    }

    void updateState()
    {
        setNeedsSave(!(current() == m_saved));
        setRepresentsDefaults(current() == Values{DefaultEnabled, DefaultDegrees, DefaultClockwiseDown, DefaultSmooth});
    }

    void refreshStatus()
    {
        QString text;
        bool running = false;
        QFile f(StatusPath);
        if (f.open(QIODevice::ReadOnly)) {
            const QString s = QString::fromUtf8(f.readAll()).trimmed();
            running = true;
            if (s == QLatin1String("on")) {
                text = i18n("Active: circle scrolling is on");
            } else if (s == QLatin1String("off")) {
                text = i18n("Active: circle scrolling is off, the touchpad is untouched");
            } else if (s == QLatin1String("busy")) {
                text = i18n("Waiting: another program is holding the touchpad (is a test copy of circle-scroll running in a terminal?)");
            } else if (s == QLatin1String("no-touchpad")) {
                text = i18n("Running, but no touchpad was found");
            } else {
                text = i18n("Running (%1)", s);
            }
        } else {
            text = i18n("The circle-scroll service is not running, so changes here won't do anything yet.");
        }
        if (text != m_statusText || running != m_serviceRunning) {
            m_statusText = text;
            m_serviceRunning = running;
            Q_EMIT statusChanged();
        }
    }

    KSharedConfigPtr m_config;
    bool m_enabled = DefaultEnabled;
    int m_degrees = DefaultDegrees;
    bool m_clockwiseDown = DefaultClockwiseDown;
    bool m_smooth = DefaultSmooth;
    Values m_saved{DefaultEnabled, DefaultDegrees, DefaultClockwiseDown, DefaultSmooth};
    QString m_statusText;
    bool m_serviceRunning = false;
    QTimer m_statusTimer;
};

K_PLUGIN_CLASS_WITH_JSON(CircleScrollKcm, "kcm_circlescroll.json")

#include "kcm_circlescroll.moc"
