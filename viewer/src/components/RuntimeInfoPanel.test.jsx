import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import RuntimeInfoPanel from './RuntimeInfoPanel'

describe('RuntimeInfoPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('renders runtime details on desktop variant', () => {
    render(
      <RuntimeInfoPanel
        runtimeInfo={{ viewer_port: 5051, default_viewer_port: 5050, project_root: '/tmp/WUDD.ai' }}
        activePort="5051"
      />,
    )

    expect(screen.getByText('Runtime')).toBeInTheDocument()
    expect(screen.getByText('Port 5051')).toBeInTheDocument()
    expect(screen.getByText('WUDD.ai')).toBeInTheDocument()
  })

  it('copies runtime details from compact variant', async () => {
    render(
      <RuntimeInfoPanel
        runtimeInfo={{ viewer_port: 5052, default_viewer_port: 5050, project_root: '/tmp/WUDD.ai' }}
        activePort="5052"
        compact
      />,
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copier les infos runtime' }))
    })

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      'Port: 5052\nPort par défaut: 5050\nProjet: WUDD.ai\nRacine: /tmp/WUDD.ai',
    )

    act(() => {
      vi.advanceTimersByTime(2000)
    })
  })
})