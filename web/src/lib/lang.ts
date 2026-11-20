const GREEK = /\p{Script=Greek}/gu;
const LATIN = /\p{Script=Latin}/gu;

/**
 * The `lang` attribute for a piece of user content: Greek when most of its letters are,
 * so screen readers pronounce it and browsers hyphenate it correctly.
 */
export function textLang(text: string): "el" | undefined {
  const greek = text.match(GREEK)?.length ?? 0;
  return greek > 0 && greek >= (text.match(LATIN)?.length ?? 0) ? "el" : undefined;
}
