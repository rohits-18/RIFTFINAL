import React from 'react';
import { useStore } from '../store/useStore';
import { CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react';

const formatTime = (ts: string | null | undefined) => ts ? new Date(ts).toLocaleTimeString() : '';

const Timeline = () => {
    const { currentResult } = useStore();

    if (!currentResult) return null;

    const events: string[] = Array.isArray(currentResult.ci_timeline) ? currentResult.ci_timeline : [];
    if (events.length === 0) return null;

    const isFinal = ['RESOLVED', 'FAILED', 'PARTIAL'].includes(currentResult.ci_status);
    const isResolved = currentResult.ci_status === 'RESOLVED';
    const isPartial = currentResult.ci_status === 'PARTIAL';

    const cleanEvent = (msg: string) => {
        if (msg.includes("Bad git executable")) {
            return "Critical Error: System failed to find 'git' on the server. Deployment environment restriction detected.";
        }
        if (msg.includes("Failed to talk to backend at /api")) {
            return "Connection Error: The backend API did not respond. Check your internet or server health.";
        }
        // General cleanup: remove long stack traces or technically verbose phrases
        return msg.split("Example: export GIT_PYTHON_REFRESH=quiet")[0].trim();
    };

    return (
        <div className="bg-gradient-to-br from-slate-800 to-slate-800/80 rounded-2xl border border-slate-700/60 overflow-hidden shadow-2xl mt-6">
            <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
                <h2 className="text-sm font-black uppercase tracking-widest text-slate-300 flex items-center gap-2">
                    ⏳ Execution Timeline
                </h2>
                <div className="flex items-center gap-3">
                    <span className="text-[11px] text-blue-400 font-mono font-bold bg-blue-900/30 px-2 py-0.5 rounded-md border border-blue-800/50">
                        {currentResult.iterations_used ?? 0} / {currentResult.max_retries ?? 5} ITERATIONS
                    </span>
                    <span className="text-[11px] text-slate-500 font-mono">{events.length} events</span>
                </div>
            </div>

            <div className="px-6 py-4">
                <div className="relative border-l-2 border-slate-700 ml-2 space-y-4">
                    {events.map((event, idx) => {
                        const eventStr = typeof event === 'string' ? event : JSON.stringify(event);
                        const cleanedEvent = cleanEvent(eventStr);
                        const isLast = idx === events.length - 1;
                        const isErr = cleanedEvent.toLowerCase().includes('error') || cleanedEvent.toLowerCase().includes('fail');
                        const isOk = cleanedEvent.toLowerCase().includes('pass') || cleanedEvent.toLowerCase().includes('success') || cleanedEvent.toLowerCase().includes('resolv');

                        return (
                            <div key={idx} className="relative pl-8">
                                {/* dot */}
                                <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 flex items-center justify-center
                                    ${isErr ? 'bg-red-900 border-red-500' : isOk ? 'bg-emerald-900 border-emerald-500' : isLast && !isFinal ? 'bg-blue-900 border-blue-500' : 'bg-slate-800 border-slate-600'}`}>
                                    <div className={`w-1.5 h-1.5 rounded-full ${isLast && !isFinal ? 'animate-ping bg-blue-400' : isErr ? 'bg-red-400' : isOk ? 'bg-emerald-400' : 'bg-slate-400'}`} />
                                </div>

                                <div className={`bg-slate-900/50 p-3 rounded-xl border ${isErr ? 'border-red-900/40' : isOk ? 'border-emerald-900/40' : 'border-slate-700/50'} hover:border-slate-600/60 transition-colors`}>
                                    <div className="flex items-start gap-2">
                                        <span className="font-mono text-[10px] text-blue-400/60 flex-shrink-0 mt-0.5">
                                            [{String(idx + 1).padStart(2, '0')}]
                                        </span>
                                        <p className={`text-xs leading-relaxed ${isErr ? 'text-red-300' : isOk ? 'text-emerald-300' : 'text-slate-300'}`}>
                                            {cleanedEvent}
                                        </p>
                                        {isLast && !isFinal && (
                                            <Loader2 className="w-3 h-3 text-blue-400 animate-spin flex-shrink-0 ml-auto" />
                                        )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}

                    {/* Terminal status */}
                    {isFinal && (
                        <div className="relative pl-8">
                            <div className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 flex items-center justify-center ${isResolved ? 'bg-emerald-900 border-emerald-500' :
                                isPartial ? 'bg-amber-900 border-amber-500' :
                                    'bg-red-900 border-red-500'
                                }`}>
                                {isResolved && <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400" />}
                                {isPartial && <CheckCircle2 className="w-2.5 h-2.5 text-amber-400 opacity-80" />}
                                {!isResolved && !isPartial && <XCircle className="w-2.5 h-2.5 text-red-400" />}
                            </div>
                            <div className={`p-3 rounded-xl border font-black text-sm text-center uppercase tracking-widest ${isResolved ? 'border-emerald-700/50 bg-emerald-900/20 text-emerald-400' :
                                isPartial ? 'border-amber-700/50 bg-amber-900/20 text-amber-400' :
                                    'border-red-700/50 bg-red-900/20 text-red-400'
                                }`}>
                                {isResolved ? '✅ All Tests Passed — CI RESOLVED' :
                                    isPartial ? '⚡ Partial Fix Applied — Static Issues Addressed' :
                                        '❌ Agent Exhausted Retries — CI FAILED'}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default Timeline;
