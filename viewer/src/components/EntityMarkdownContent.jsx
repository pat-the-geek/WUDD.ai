import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function EntityMarkdownContent({ content, components }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  )
}