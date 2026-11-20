cmake_minimum_required(VERSION 3.20)
project(kcm_circlescroll)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ECM 6.0 REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Qml Quick)
find_package(KF6 6.0 REQUIRED COMPONENTS KCMUtils Config CoreAddons I18n)

add_definitions(-DTRANSLATION_DOMAIN=\"kcm_circlescroll\")

# Builds the plugin, bundles ui/main.qml into it, and installs it where
# System Settings looks (plasma/kcms/systemsettings), plus its .desktop entry.
kcmutils_add_qml_kcm(kcm_circlescroll SOURCES kcm_circlescroll.cpp)

target_link_libraries(kcm_circlescroll PRIVATE
    Qt6::Core
    Qt6::Qml
    KF6::KCMUtilsQuick
    KF6::ConfigCore
    KF6::CoreAddons
    KF6::I18n
)
