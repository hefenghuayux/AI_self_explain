declare module "katex/contrib/auto-render" {
  import type { KatexOptions } from "katex"

  interface Delimiter {
    left: string
    right: string
    display: boolean
  }

  interface AutoRenderOptions extends KatexOptions {
    delimiters?: Delimiter[]
  }

  export default function renderMathInElement(element: HTMLElement, options?: AutoRenderOptions): void
}
