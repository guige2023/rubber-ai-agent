import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Markdown } from './Markdown';
import { useI18n } from '../hooks/useI18n';

vi.mock('../hooks/useI18n', () => ({
  useI18n: vi.fn(),
}));

const mockedUseI18n = vi.mocked(useI18n);
const clipboardWriteText = vi.fn();

describe('Markdown', () => {
  beforeEach(() => {
    clipboardWriteText.mockReset();

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: clipboardWriteText.mockResolvedValue(undefined),
      },
    });

    mockedUseI18n.mockReturnValue({
      locale: 'en',
      changeLanguage: vi.fn(),
      t: (key: string) =>
        (
          {
            'common.copy': 'Copy',
            'common.copied': 'Copied',
          } as Record<string, string>
        )[key] ?? key,
    });
  });

  it('copies fenced code blocks from the top-right action', async () => {
    render(
      <Markdown
        content={[
          '```markdown',
          '# Optimized Prompt',
          '- hard signal 1',
          '- hard signal 2',
          '```',
        ].join('\n')}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledWith('# Optimized Prompt\n- hard signal 1\n- hard signal 2');
    });

    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('updates the copy button label when parent translations change', () => {
    mockedUseI18n
      .mockReturnValueOnce({
        locale: 'en',
        changeLanguage: vi.fn(),
        t: (key: string) =>
          (
            {
              'common.copy': 'Copy',
              'common.copied': 'Copied',
            } as Record<string, string>
          )[key] ?? key,
      })
      .mockReturnValueOnce({
        locale: 'zh',
        changeLanguage: vi.fn(),
        t: (key: string) =>
          (
            {
              'common.copy': '复制',
              'common.copied': '已复制',
            } as Record<string, string>
          )[key] ?? key,
      });

    const content = ['```markdown', '# Prompt', '```'].join('\n');
    const { rerender } = render(<Markdown content={content} />);

    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();

    rerender(<Markdown content={content} />);

    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
  });
});
