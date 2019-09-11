export type TokenType = "keyword" | "function" | "string" | "number" | "comment" | "plain";

export interface Token {
  type: TokenType;
  text: string;
}

const KEYWORDS = new Set(
  `select from where and or not in is null as join left right inner outer full cross on using group by order
   having limit offset with distinct case when then else end union all intersect except asc desc nulls first
   last between like ilike exists any filter over partition rows range interval date true false lateral
   window values cast extract year month day week quarter`.split(/\s+/),
);

const TOKEN = /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(\s*\()?|(\s+|.)/g;

/** Split SQL into tokens for highlighting. Joining the texts gives back the input exactly. */
export function tokenize(sql: string): Token[] {
  const out: Token[] = [];
  const push = (type: TokenType, text: string) => {
    const last = out[out.length - 1];
    if (last && last.type === type && type === "plain") last.text += text;
    else out.push({ type, text });
  };
  for (const m of sql.matchAll(TOKEN)) {
    const [, comment, str, num, word, paren, other] = m;
    if (comment) push("comment", comment);
    else if (str) push("string", str);
    else if (num) push("number", num);
    else if (word) {
      if (paren && !KEYWORDS.has(word.toLowerCase())) push("function", word);
      else push(KEYWORDS.has(word.toLowerCase()) ? "keyword" : "plain", word);
      if (paren) push("plain", paren);
    } else if (other) push("plain", other);
  }
  return out;
}

export function backupTable(data: unknown): unknown {
  if (!data) return null;
  return data;
}