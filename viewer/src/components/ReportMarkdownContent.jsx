import { Component } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

class ReportMarkdownErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, errorMessage: '' }
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      errorMessage: error?.message || 'Erreur de rendu Markdown',
    }
  }

  componentDidUpdate(prevProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, errorMessage: '' })
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="my-6 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-300">
          <p className="font-semibold">Le rendu du rapport a échoué.</p>
          <p className="mt-1 break-words">{this.state.errorMessage}</p>
          <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-rose-100 bg-white p-3 text-xs text-slate-700 dark:border-rose-900 dark:bg-slate-950 dark:text-slate-300 whitespace-pre-wrap">
            {this.props.rawMarkdown}
          </pre>
        </div>
      )
    }

    return this.props.children
  }
}

export default function ReportMarkdownContent({ md, components }) {
  return (
    <ReportMarkdownErrorBoundary resetKey={md} rawMarkdown={md}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={components}
      >
        {md}
      </ReactMarkdown>
    </ReportMarkdownErrorBoundary>
  )
}