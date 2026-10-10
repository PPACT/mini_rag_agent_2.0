/**
 * 答案的 Markdown 渲染（`前端ui设计.md` §2.2：**AI 回答必须是最前面的 Markdown**）。
 *
 * ⚠️ `react-markdown` **默认不渲染裸 HTML** —— 这正合本项目的只读定位，
 *    ⛔ 别为了"支持富文本"去开 `rehype-raw`（那等于把 XSS 面打开）。
 */
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function MarkdownBody({ text }: { text: string }) {
  return (
    <div className="md-body">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  )
}
