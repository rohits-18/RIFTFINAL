import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import { CheckCircle2, XCircle, Code, FileText, ChevronDown, ChevronUp, Hash } from 'lucide-react';

// Map error type to readable label and color
const errorTypeStyle = (type: string) => {
    const t = type?.toUpperCase() || '';
    if (t.includes('LINTING') || t.includes('LINT')) return 'bg-yellow-900/30 text-yellow-300 border-yellow-700/50';
    if (t.includes('SYNTAX')) return 'bg-orange-900/30 text-orange-300 border-orange-700/50';
    if (t.includes('TYPE')) return 'bg-purple-900/30 text-purple-300 border-purple-700/50';
    if (t.includes('IMPORT')) return 'bg-cyan-900/30 text-cyan-300 border-cyan-700/50';
    if (t.includes('INDENT')) return 'bg-pink-900/30 text-pink-300 border-pink-700/50';
    if (t.includes('LOGIC')) return 'bg-blue-900/30 text-blue-300 border-blue-700/50';
    return 'bg-slate-700/50 text-slate-300 border-slate-600';
};

const FixTable = () => {
    const { currentResult } = useStore();
    const [expandedRow, setExpandedRow] = useState<number | null>(null);

    if (!currentResult || !currentResult.fixes || currentResult.fixes.length === 0) return null;

    const fixes = currentResult.fixes;

    const toggleRow = (idx: number) =>
        setExpandedRow(expandedRow === idx ? null : idx);

    return (
        <div className="bg-gradient-to-br from-slate-800 to-slate-800/80 rounded-2xl border border-slate-700/60 overflow-hidden shadow-2xl mt-6">
            <div className="px-6 py-4 border-b border-slate-700/50">
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-300 flex items-center gap-2">
                    🛠️ Fix Manifest
                </h2>
                <p className="text-[11px] text-slate-500 mt-0.5">{fixes.length} fix{fixes.length !== 1 ? 'es' : ''} applied — click any row to inspect the diff</p>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead>
                        <tr className="bg-slate-900/60 text-[10px] font-black text-slate-500 uppercase tracking-widest border-b border-slate-700/50">
                            <th className="px-6 py-3">Status</th>
                            <th className="px-6 py-3">File</th>
                            <th className="px-6 py-3">Bug Type</th>
                            <th className="px-6 py-3">Line #</th>
                            <th className="px-6 py-3">Commit</th>
                            <th className="px-6 py-3 text-center">Expand</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30">
                        {fixes.map((fix, idx) => (
                            <React.Fragment key={idx}>
                                <tr
                                    onClick={() => toggleRow(idx)}
                                    className={`cursor-pointer transition-all hover:bg-slate-700/20 ${expandedRow === idx ? 'bg-slate-700/10' : ''}`}
                                >
                                    {/* Status */}
                                    <td className="px-6 py-3.5">
                                        {fix.tests_passed ? (
                                            <span id={`fix-status-${idx}`} className="inline-flex items-center gap-1.5 text-emerald-400 font-black text-[11px] bg-emerald-900/20 px-2.5 py-1 rounded-full border border-emerald-700/40">
                                                <CheckCircle2 className="w-3 h-3" /> ✓ Fixed
                                            </span>
                                        ) : (
                                            <span id={`fix-status-${idx}`} className="inline-flex items-center gap-1.5 text-red-400 font-black text-[11px] bg-red-900/20 px-2.5 py-1 rounded-full border border-red-700/40">
                                                <XCircle className="w-3 h-3" /> ✗ Failed
                                            </span>
                                        )}
                                    </td>

                                    {/* File */}
                                    <td className="px-6 py-3.5 max-w-[180px]">
                                        <span className="flex items-center gap-1.5 text-slate-300 text-xs font-mono truncate" title={fix.file_path}>
                                            <FileText className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
                                            <span className="truncate">{fix.file_path}</span>
                                        </span>
                                    </td>

                                    {/* Bug Type */}
                                    <td className="px-6 py-3.5">
                                        <span className={`inline-block px-2.5 py-1 rounded-lg text-[10px] font-black border uppercase tracking-wide ${errorTypeStyle(fix.error_type)}`}>
                                            {fix.error_type?.replace('FailureType.', '') || 'UNKNOWN'}
                                        </span>
                                    </td>

                                    {/* Line # */}
                                    <td className="px-6 py-3.5">
                                        <span className="flex items-center gap-1 text-slate-400 text-xs font-mono">
                                            <Hash className="w-3 h-3 text-slate-600" />
                                            {fix.line_number ?? '—'}
                                        </span>
                                    </td>

                                    {/* Commit Message */}
                                    <td className="px-6 py-3.5 max-w-[200px]">
                                        <span className="text-[10px] text-slate-500 font-mono truncate block" title={fix.commit_message ?? ''}>
                                            {fix.commit_message || '—'}
                                        </span>
                                    </td>

                                    {/* Expand toggle */}
                                    <td className="px-6 py-3.5 text-center text-slate-500">
                                        {expandedRow === idx
                                            ? <ChevronUp className="w-4 h-4 inline text-blue-400" />
                                            : <ChevronDown className="w-4 h-4 inline" />
                                        }
                                    </td>
                                </tr>

                                {/* Expanded diff row */}
                                {expandedRow === idx && (
                                    <tr className="bg-slate-900/50">
                                        <td colSpan={6} className="px-6 py-4">
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                <div className="bg-red-950/30 rounded-xl p-4 border border-red-900/30">
                                                    <h4 className="text-red-400 font-black text-[10px] uppercase tracking-widest mb-2 flex items-center gap-1.5">
                                                        <Code className="w-3 h-3" /> Original
                                                    </h4>
                                                    <pre className="text-xs text-red-200/80 font-mono overflow-x-auto bg-red-950/40 p-3 rounded-lg leading-relaxed whitespace-pre-wrap break-all">
                                                        {fix.original_snippet || '(no snippet available)'}
                                                    </pre>
                                                </div>
                                                <div className="bg-emerald-950/30 rounded-xl p-4 border border-emerald-900/30">
                                                    <h4 className="text-emerald-400 font-black text-[10px] uppercase tracking-widest mb-2 flex items-center gap-1.5">
                                                        <Code className="w-3 h-3" /> Patched
                                                    </h4>
                                                    <pre className="text-xs text-emerald-200/80 font-mono overflow-x-auto bg-emerald-950/40 p-3 rounded-lg leading-relaxed whitespace-pre-wrap break-all">
                                                        {fix.patched_snippet || '(no snippet available)'}
                                                    </pre>
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default FixTable;
