export function knownCitationIndexes(markers: string, known: ReadonlySet<number>) {
  return markers.replace(/\[(\d+)\]/g, (whole, value: string) =>
    known.has(Number(value)) ? `⟦${value}⟧` : whole,
  );
}

export function protectMarkdownCode(text: string, transform: (value: string) => string) {
  const parts = text.split(/(```[\s\S]*?```|`[^`\n]+`)/g);
  return parts.map((part, index) => (index % 2 === 1 ? part : transform(part))).join("");
}
