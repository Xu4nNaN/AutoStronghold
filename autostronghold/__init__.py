"""AutoStronghold: automatic badge farming for Arknights "Stronghold Protocol" (卫戍协议).

The package is organised in layers; each layer only depends on the ones listed before it:

    paths / variant / errors / log      process-wide basics
    geometry                            fixed 1920x1080 UI coordinates
    device                              screenshots and touch input (emulator / PC client)
    vision                              OCR and image detectors (pure functions on images)
    game                                screen recognition and in-game procedures
    tactics                             how to spend gold and where to deploy (pluggable)
    features                            what to farm (蚀刻章 / 全角标金标 / 全角标彩标)
    extensions                          extension points for later work (squads, levels, assistant)
    session / gui                       one run, and the window that starts it (the program)
"""

__version__ = "1.0.0"
