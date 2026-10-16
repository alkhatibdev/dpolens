export interface Piece {
  /** As its own wording has it, with the space before it. */
  text: string;
  change: "same" | "added" | "removed";
}

interface Token {
  space: string;
  word: string;
}

/** Past this many token pairs, a clause is shown as replaced rather than compared word by word. */
const MOST_PAIRS = 1_000_000;

/** Words, and each mark of punctuation on its own, so "years," and "years" share "years". */
function tokens(text: string): Token[] {
  return [...text.matchAll(/(\s*)([\p{L}\p{N}\p{M}]+|[^\s\p{L}\p{N}\p{M}])/gu)].map((found) => ({
    space: found[1] ? " " : "",
    word: found[2] ?? "",
  }));
}

/**
 * What changed between two wordings, word by word: the longest run of words the
 * two share stays as it is, and the rest is marked added or removed.
 */
export function wordDiff(before: string, after: string): Piece[] {
  const old = tokens(before);
  const now = tokens(after);
  const pieces: Piece[] = [];
  const push = ({ space, word }: Token, change: Piece["change"]) => {
    const text = pieces.length ? space + word : word;
    const last = pieces[pieces.length - 1];
    if (last && last.change === change) {
      last.text += text;
    } else {
      pieces.push({ text, change });
    }
  };
  if (old.length * now.length > MOST_PAIRS) {
    old.forEach((token) => push(token, "removed"));
    now.forEach((token) => push(token, "added"));
    return pieces;
  }
  // shared[i * width + j]: how many tokens old[i..] and now[j..] share, in order.
  const width = now.length + 1;
  const shared = new Uint32Array((old.length + 1) * width);
  const at = (i: number, j: number) => shared[i * width + j] ?? 0;
  for (let i = old.length - 1; i >= 0; i--) {
    for (let j = now.length - 1; j >= 0; j--) {
      shared[i * width + j] =
        old[i]?.word === now[j]?.word ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
    }
  }
  let i = 0;
  let j = 0;
  while (i < old.length || j < now.length) {
    const was = old[i];
    const is = now[j];
    if (was && is && was.word === is.word) {
      push(is, "same");
      i += 1;
      j += 1;
    } else if (was && (!is || at(i + 1, j) >= at(i, j + 1))) {
      push(was, "removed");
      i += 1;
    } else if (is) {
      push(is, "added");
      j += 1;
    }
  }
  return pieces;
}
