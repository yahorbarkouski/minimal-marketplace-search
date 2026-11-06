import { HeatMap } from "@/components/heat/heat-map"

/**
 * The name as a heat map above the search box on the start page, grey until the hand comes. 300 by 82 draws
 * capitals about 43px tall; the results page leaves the name out.
 */
export function Wordmark() {
  return <HeatMap shape="Word" word="CURATED" cycle={["Word"]} width={300} height={82} label="Curated" />
}
