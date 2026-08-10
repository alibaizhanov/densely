"""densely CLI: compress / decompress / stats."""

import argparse
import sys

from densely import compress, decompress, ntok


def main():
    p = argparse.ArgumentParser(prog="densely", description="lossless context compression for LLMs")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress", help="file -> dense payload (stdout or -o)")
    c.add_argument("file")
    c.add_argument("-o", "--output")
    c.add_argument("--backend", choices=["lzma", "neural"], default="lzma")

    d = sub.add_parser("decompress", help="payload file -> original (stdout or -o)")
    d.add_argument("file")
    d.add_argument("-o", "--output")

    s = sub.add_parser("stats", help="show token savings for files (no output written)")
    s.add_argument("files", nargs="+")

    args = p.parse_args()

    if args.cmd == "compress":
        text = open(args.file, encoding="utf-8").read()
        payload = compress(text, backend=args.backend)
        if decompress(payload) != text:
            sys.exit("round-trip verification failed, refusing to write output")
        _write(args.output, payload)
    elif args.cmd == "decompress":
        payload = open(args.file, encoding="utf-8").read()
        _write(args.output, decompress(payload))
    elif args.cmd == "stats":
        total_o = total_p = 0
        for path in args.files:
            text = open(path, encoding="utf-8").read()
            payload = compress(text)
            ok = decompress(payload) == text
            o, c_ = ntok(text), ntok(payload)
            total_o += o
            total_p += c_
            print(f"{path}: {o} -> {c_} tokens "
                  f"({o / c_:.2f}x, saved {100 * (1 - c_ / o):.1f}%), "
                  f"round-trip {'OK' if ok else 'FAILED'}")
        if len(args.files) > 1:
            print(f"TOTAL: {total_o} -> {total_p} tokens "
                  f"({total_o / total_p:.2f}x, saved {100 * (1 - total_p / total_o):.1f}%)")


def _write(output, content):
    if output:
        open(output, "w", encoding="utf-8").write(content)
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    main()
