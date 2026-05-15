import { useEffect, useRef, useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { invoke } from '@tauri-apps/api/core';
import { Check, Copy } from 'lucide-react';

import { useI18n } from '../hooks/useI18n';

interface MarkdownProps {
  content: string;
}

function CopyCodeButton({ text, t }: { text: string; t: (key: string) => string }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);

      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }

      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
      }, 1800);
    } catch (error) {
      console.error('Failed to copy code block:', error);
    }
  };

  return (
    <button
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void handleCopy();
      }}
      aria-label={copied ? t('common.copied') : t('common.copy')}
      title={copied ? t('common.copied') : t('common.copy')}
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/45 text-white/60 backdrop-blur-md transition-colors hover:border-white/20 hover:text-white"
    >
      {copied ? <Check size={14} strokeWidth={2.4} /> : <Copy size={14} strokeWidth={2.1} />}
    </button>
  );
}

export const Markdown = ({ content }: MarkdownProps) => {
  const { t } = useI18n();

  const isAbsoluteLocalPath = (value?: string) => {
    return Boolean(value && (value.startsWith('/') || /^[a-zA-Z]:(?:\\|\/)/.test(value)));
  };

  return (
    <div className="prose prose-invert max-w-none [overflow-wrap:anywhere] prose-p:leading-relaxed prose-pre:bg-[#0d0d0d] prose-pre:border prose-pre:border-white/5 prose-code:text-blue-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => {
          if (url.startsWith('file://')) {
            return url;
          }
          return defaultUrlTransform(url);
        }}
        components={{
        code({ node, inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '');
          // Deep extract string from React children array if needed.
          let text = '';
          if (Array.isArray(children)) {
            text = children.map(c => typeof c === 'string' ? c : '').join('');
          } else {
            text = String(children || '');
          }
          text = text.replace(/^\s+|\s+$/g, ''); // Trim all leading/trailing whitespace including newlines

          const isAbsolutePath = text.startsWith('/') || /^[a-zA-Z]:(?:\\|\/)/.test(text);

          if (isAbsolutePath) {
            const handleOpenPath = async (e: React.MouseEvent) => {
              e.preventDefault();
              e.stopPropagation();
              try {
                // Try Tauri command first (works in Tauri app)
                await invoke('open_local_file', { path: text });
              } catch {
                // Fallback for development mode
                try {
                  const fileUrl = `file://${text}`;
                  window.open(fileUrl, '_blank');
                } catch {
                  // Last resort: copy path to clipboard
                  await navigator.clipboard.writeText(text);
                  alert(`路径已复制到剪贴板:\n${text}`);
                }
              }
            };

            return (
              <span
                className="bg-white/10 px-1.5 py-0.5 rounded text-blue-400 hover:text-blue-300 font-mono text-[0.9em] cursor-pointer hover:underline transition-colors"
                onClick={handleOpenPath}
                title={`点击打开文件: ${text}`}
              >
                {children}
              </span>
            );
          }

          if (!inline) {
            return (
              <div className="group/code relative my-4 [overflow-wrap:normal]">
                <div className="absolute right-3 top-3 z-10 opacity-0 transition-opacity duration-150 group-hover/code:opacity-100 group-focus-within/code:opacity-100">
                  <CopyCodeButton text={text} t={t} />
                </div>
                <SyntaxHighlighter
                  style={vscDarkPlus as any}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  className="rounded-xl !my-0 border border-white/5"
                  customStyle={{
                    margin: 0,
                    borderRadius: '0.75rem',
                    background: '#0d0d0d',
                  }}
                  {...props}
                >
                  {text}
                </SyntaxHighlighter>
              </div>
            );
          }

          return (
            <code className="bg-white/10 px-1.5 py-0.5 rounded text-blue-300 font-mono text-[0.9em]" {...props}>
              {children}
            </code>
          );
        },
        a({ node, children, href, ...props }: any) {
          const isFileUrl = href?.startsWith('file://');
          const isLocalPath = isAbsoluteLocalPath(href);
          if (isFileUrl || isLocalPath) {
            const rawPath = isFileUrl ? href.replace('file://', '') : href;
            // Handle local file path decoding and normalization
            const decodedPath = decodeURIComponent(rawPath);
            // On Windows, the path might look like /C:/User...
            const cleanPath = decodedPath.replace(/^\/([a-zA-Z]:)/, '$1');

            const handleOpenFile = async (e: React.MouseEvent) => {
              e.preventDefault();
              e.stopPropagation();
              try {
                // Try Tauri command first (works in Tauri app)
                await invoke('open_local_file', { path: cleanPath });
              } catch {
                // Fallback for development mode: try using file:// URL
                try {
                  // macOS can open file:// URLs directly
                  window.open(href, '_blank');
                } catch {
                  // Last resort: copy path to clipboard
                  await navigator.clipboard.writeText(cleanPath);
                  alert(`路径已复制到剪贴板:\n${cleanPath}`);
                }
              }
            };

            return (
              <a
                {...props}
                className="cursor-pointer break-words text-blue-400 underline transition-colors [overflow-wrap:anywhere] hover:text-blue-300"
                onClick={handleOpenFile}
              >
                {children}
              </a>
            );
          }
          return <a className="break-words text-blue-400 underline transition-colors [overflow-wrap:anywhere] hover:text-blue-300" target="_blank" rel="noopener noreferrer" href={href} {...props}>{children}</a>;
        },
        img({ node, src, alt, ...props }: any) {
          if (!src) return null;

          const isLocalFile = src.startsWith('file://') || isAbsoluteLocalPath(src);

          const handleImageClick = async (e: React.MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();

            if (isLocalFile) {
              const rawPath = src.startsWith('file://') ? src.replace('file://', '') : src;
              const decodedPath = decodeURIComponent(rawPath);
              const cleanPath = decodedPath.replace(/^\/([a-zA-Z]:)/, '$1');

              try {
                // Try Tauri command first
                await invoke('open_local_file', { path: cleanPath });
              } catch {
                // Fallback: try window.open with file URL
                try {
                  window.open(src, '_blank');
                } catch {
                  // Last resort: copy path
                  await navigator.clipboard.writeText(cleanPath);
                  alert(`图片路径已复制到剪贴板:\n${cleanPath}`);
                }
              }
            } else {
              // For remote URLs, open in new tab
              window.open(src, '_blank');
            }
          };

          return (
            <div className="relative group/image my-2">
              <img
                src={src}
                alt={alt || ''}
                {...props}
                className="max-w-full h-auto rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
                onClick={handleImageClick}
                onError={(e) => {
                  // Fallback to text display if image fails to load
                  const target = e.target as HTMLImageElement;
                  target.style.display = 'none';
                  const parent = target.parentElement;
                  if (parent) {
                    parent.innerHTML = `<span class="text-red-400 text-sm">图片加载失败: ${alt || src}</span>`;
                  }
                }}
              />
              <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover/image:opacity-100 transition-opacity pointer-events-none">
                <div className="bg-black/60 text-white text-xs px-2 py-1 rounded">
                  {isLocalFile ? '点击打开图片' : '点击查看原图'}
                </div>
              </div>
            </div>
          );
        }

      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
};
