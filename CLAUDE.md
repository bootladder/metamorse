metamorse 

the next level of meta key.  the meta key is the morse code key.
you can use the meta key to do dot and dash.
and you can dispatch from there.

think of it like CTRL+$ANYKEY at the basic level,
or emacs chords and whichkey at the next level
or like spacemacs' "fd" stroke combo

but this is simply just adding another dimension to the already existing meta key.

ARCHITECTURE

X11 Window System 
a hook or event listener needs to be installed
a timer will be used to demodulate key stroke up and down into 
something that can then be decoded into dot dash and then letters.

those letters then simply dispatch into some switch.


User Interface
assume competent UNIX user that can make use of help files and config files.


Installation
comprehensive non invasive,  fully transparent walking through the user of whats happening

TBD ARCHITECTURE
