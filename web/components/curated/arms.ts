/** What each ranking searches. */
export const ARM_DESCRIPTIONS: Record<string, string> = {
  keyword: "BM25 over name, brand, attributes, the editor's text and buyer searches.",
  text: "The search's embedding against each product's catalogue card.",
  photo: "The search's embedding against each product's photos.",
  facets: "The decision model's reading of the search against each product's category and attribute tags.",
  style: "The search's embedding against each product's style description.",
  text_interpretation: "The interpretation's embedding against each product's catalogue card.",
  photo_interpretation: "The interpretation's embedding against each product's photos.",
  style_interpretation: "The interpretation, as a document, against each product's style description.",
}

export const ARM_LABELS: Record<string, string> = {
  keyword: "Keywords",
  text: "Text",
  photo: "Photo",
  facets: "Facets",
  style: "Style",
  text_interpretation: "Text, interpreted",
  photo_interpretation: "Photo, interpreted",
  style_interpretation: "Style, interpreted",
}

/** The rankings in the order the search runs them, with the one- or two-letter heading of their table column. */
export const ARM_COLUMNS: readonly { name: string; column: string }[] = [
  { name: "keyword", column: "K" },
  { name: "text", column: "T" },
  { name: "photo", column: "P" },
  { name: "facets", column: "F" },
  { name: "style", column: "S" },
  { name: "text_interpretation", column: "Tᵢ" },
  { name: "photo_interpretation", column: "Pᵢ" },
  { name: "style_interpretation", column: "Sᵢ" },
]
