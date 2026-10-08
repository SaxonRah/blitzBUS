/**
 * Calculate Doom 1.9s Frames Per Second (32KiB lazy libc EXE edition).
 * 2023-09-19 Thomas Perl <m@thp.io>
 *
 * This program will read the text output from the text mode
 * video memory buffer and calculate the based on the gametics
 * and realtics displayed (because you have, after all, a
 * COMPUTER in front of you).
 **/

#include <stdio.h>
#include <dos.h>

int main(int argc, char *argv[])
{
    // Textmode starts at B800:0000 (0xB8000 linear)
    char far *textmode = MK_FP(0xB800, 0x0000);

    char first_line[80] = {0};
    for (int i=0; i<sizeof(first_line)-1; ++i) {
        // Text mode layout is 1 character byte, 1 attribute byte,
        // so advance 2 bytes for every character read on-screen.
        first_line[i] = textmode[i*2+0];
    }

    long gametics, realtics;
    int n = sscanf(first_line, "timed %ld gametics in %ld realtics", &gametics, &realtics);

    if (n == 2) {
        printf("FPS: %.2f\n", 35.0 * (double)gametics / (double)realtics);
    } else {
        printf("I see nothing. Run 'doom -timedemo demo3' first.\n");
    }

    return 0;
}
