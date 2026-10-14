import Markdown from 'react-markdown';

// No links, images, raw HTML, custom components or payload-supplied attributes.
export function LessonMarkdown({ children }: { children: string }) {
  return <Markdown skipHtml unwrapDisallowed allowedElements={['p', 'strong', 'em', 'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr', 'br']}>{children}</Markdown>;
}
