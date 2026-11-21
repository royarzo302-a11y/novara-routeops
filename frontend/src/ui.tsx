import { cloneElement, isValidElement, useId, type InputHTMLAttributes, type ReactElement, type ReactNode } from 'react'
import { CircleAlert, LoaderCircle } from 'lucide-react'

export function Field({ label, children, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; children?: ReactNode }) {
  const labelId = useId()
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<{ 'aria-labelledby'?: string }>, { 'aria-labelledby': labelId })
    : <input {...props} aria-labelledby={labelId} />
  return <label className="field"><span id={labelId}>{label}</span>{control}</label>
}

export function Panel({ title, description, action, children, className = '' }: {
  title: string; description?: string; action?: ReactNode; children: ReactNode; className?: string
}) {
  const heading = useId()
  return <section className={'panel ' + className} aria-labelledby={heading}>
    <header className="panel-head"><div><h2 id={heading}>{title}</h2>{description && <p>{description}</p>}</div>{action}</header>
    {children}
  </section>
}

export function Notice({ text, error = false }: { text: string; error?: boolean }) {
  return <div className={'notice ' + (error ? 'error' : '')} role={error ? 'alert' : 'status'}><CircleAlert size={17} />{text}</div>
}

export function Busy({ children }: { children: ReactNode }) {
  return <><LoaderCircle size={16} className="spinner" />{children}</>
}

export function VanArt() {
  return <svg className="van-art" viewBox="0 0 180 65" fill="none" aria-hidden="true">
    <path d="M16 55h150" stroke="#d9e5e3" strokeWidth="2" strokeLinecap="round"/>
    <path d="M24 45V24c0-5 4-9 9-9h84c10 0 15 6 19 12l12 5c5 2 9 6 9 11v4a5 5 0 0 1-5 5H29a5 5 0 0 1-5-5v-2Z" fill="#eef5f3" stroke="#305452" strokeWidth="2"/>
    <path d="M33 23h23v15H33zm29 0h24v15H62zm30 0h22c6 0 9 3 13 7l5 8H92z" fill="#b4cfca" stroke="#305452" strokeWidth="1.7" strokeLinejoin="round"/>
    <path d="M59 16v34m30-34v34m45-12h7m-39 5h8m41-5h6" stroke="#305452" strokeWidth="1.5" strokeLinecap="round"/>
    <circle cx="49" cy="51" r="8" fill="#233937"/><circle cx="132" cy="51" r="8" fill="#233937"/>
    <circle cx="49" cy="51" r="3" fill="#c2d8d4"/><circle cx="132" cy="51" r="3" fill="#c2d8d4"/>
  </svg>
}
