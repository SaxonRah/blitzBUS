/**
 * Calculate Doom 1.9s Frames Per Second (2kb COM edition).
 * 2023-09-19 Thomas Perl <m@thp.io>
 *
 * This program will read the text output from the text mode
 * video memory buffer and calculate the based on the gametics
 * and realtics displayed (because you have, after all, a
 * COMPUTER in front of you).
 **/

#include <i86.h>

extern void xputc(char ch);
#pragma aux xputc = \
    "mov ah, 0x02" \
    "int 0x21" \
    parm [dl] ;

extern void xputs(const char *str);
#pragma aux xputs = \
    "mov ah, 0x09" \
    "int 0x21" \
    parm [dx] ;

static inline int
number_before(char far *textmode, char ch)
{
    int off = 0;

    // scan forward to character
    while (textmode[off*2] != ch) {
        off++;

        if (off > 80) {
            return -1;
        }
    }

    // scan back to the last digit
    off -= 2;

    // scan back to space before number
    while (textmode[off*2] != ' ') {
        off--;

        if (off < 0) {
            return -1;
        }
    }

    // scan forward to first digit
    ++off;

    return off;
}

static inline long
scan_number(char far *textmode, int off)
{
    long result = 0;

    if (off == -1) {
        return -1;
    }

    while (textmode[off*2] != ' ') {
        result *= 10L;
        char ch = textmode[off*2];
        if (ch < '0' || ch > '9') {
            return -1;
        }
        result += (ch-'0');
        off++;
    }

    return result;
}

static inline void
print_number(long v, int digits)
{
    long remainder = v % 10;

    v /= 10;
    if (digits > 0 || v != 0) {
        print_number(v, digits-1);
    }

    xputc('0' + remainder);
    if (digits == 0) {
        xputc('.');
    }
}

int
main()
{
    // Textmode starts at B800:0000 (0xB8000 linear)
    char far *textmode = MK_FP(0xB800, 0x0000);

    // The string we are looking for:
    // "timed <number> gametics in <number> realtics"

    long gametics = scan_number(textmode, number_before(textmode, 'g'));
    long realtics = scan_number(textmode, number_before(textmode, 'r'));

    if (gametics != -1 && realtics != -1) {
        xputs("FPS: $");
        long fps100 = 3500L * gametics / realtics;
        print_number(fps100, 2);
    } else {
        xputs("I see nothing. Run 'doom -timedemo demo3' first.$");
    }
    xputc('\n');

    return 0;
}
