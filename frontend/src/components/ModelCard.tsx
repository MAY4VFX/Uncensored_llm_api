interface ModelCardProps {
  id: string;
  slug: string;
  displayName: string;
  paramsB: number;
  quantization: string;
  gpuType: string;
  gpuCount?: number;
  status: string;
  costInput: number;
  costOutput: number;
  description: string | null;
  hfRepo?: string;
  hfDownloads?: number | null;
  hfLikes?: number | null;
  isAdmin?: boolean;
  onDeploy?: (modelId: string) => void;
  deploying?: boolean;
}

const statusConfig: Record<string, { color: string; dot: string }> = {
  active: { color: "text-terminal-400", dot: "bg-terminal-400" },
  pending: { color: "text-yellow-500", dot: "bg-yellow-500" },
  deploying: { color: "text-blue-400", dot: "bg-blue-400" },
  inactive: { color: "text-surface-700", dot: "bg-surface-700" },
};

export default function ModelCard({
  id,
  slug,
  displayName,
  paramsB,
  quantization,
  gpuType,
  gpuCount = 1,
  status,
  costInput,
  costOutput,
  description,
  hfRepo,
  hfDownloads,
  hfLikes,
  isAdmin,
  onDeploy,
  deploying,
}: ModelCardProps) {
  const st = statusConfig[status] || statusConfig.inactive;

  return (
    <div className="ind-card group">
      <div className="flex items-start justify-between mb-4">
        <h3 className="text-sm font-mono font-semibold text-neutral-100 group-hover:text-terminal-400 transition-colors">
          {displayName}
        </h3>
        <span className={`flex items-center text-[10px] font-mono uppercase tracking-widest ${st.color}`}>
          <span className={`status-dot ${st.dot}`} />
          {status}
        </span>
      </div>

      <p className="text-surface-800 text-xs mb-4 line-clamp-2 leading-relaxed">
        {description || `${paramsB}B parameter uncensored model`}
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {[`${paramsB}B`, quantization, gpuCount > 1 ? `${gpuCount}x ${gpuType}` : gpuType].map((tag) => (
          <span key={tag} className="text-[10px] font-mono text-surface-800 border border-surface-400 px-2 py-0.5 uppercase">
            {tag}
          </span>
        ))}
      </div>

      {hfRepo && (
        <div className="flex items-center gap-3 mb-4">
          <a
            href={`https://huggingface.co/${hfRepo}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-[11px] font-mono text-surface-800 hover:text-terminal-400 transition-colors truncate"
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 120 120" fill="currentColor">
              <path d="M37.2 56.8c-1.7 0-3 1.3-3 3s1.3 3 3 3 3-1.3 3-3-1.3-3-3-3zm45.6 0c-1.7 0-3 1.3-3 3s1.3 3 3 3 3-1.3 3-3-1.3-3-3-3zM60 0C26.9 0 0 26.9 0 60s26.9 60 60 60 60-26.9 60-60S93.1 0 60 0zm0 108c-26.5 0-48-21.5-48-48S33.5 12 60 12s48 21.5 48 48-21.5 48-48 48zm24.4-45.5c3.3-2.4 5.6-6.3 5.6-10.7 0-7.3-5.9-13.2-13.2-13.2-3.2 0-6.1 1.1-8.4 3l-8.4-5.2-8.4 5.2c-2.3-1.9-5.2-3-8.4-3-7.3 0-13.2 5.9-13.2 13.2 0 4.4 2.2 8.3 5.6 10.7C30.5 66.1 27 72.5 27 79.8h6c0-7.4 6-13.4 13.4-13.4h27.2c7.4 0 13.4 6 13.4 13.4h6c0-7.3-3.5-13.7-8.6-17.3zM43.2 56.8c-3.9 0-7.2-3.2-7.2-7.2s3.2-7.2 7.2-7.2 7.2 3.2 7.2 7.2-3.3 7.2-7.2 7.2zm33.6 0c-3.9 0-7.2-3.2-7.2-7.2s3.2-7.2 7.2-7.2 7.2 3.2 7.2 7.2-3.3 7.2-7.2 7.2z"/>
            </svg>
            <span className="truncate">{hfRepo}</span>
          </a>
          <div className="flex items-center gap-2 flex-shrink-0 text-[10px] font-mono text-surface-700">
            {hfDownloads != null && (
              <span className="flex items-center gap-1" title="Downloads">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {hfDownloads >= 1000 ? `${(hfDownloads / 1000).toFixed(hfDownloads >= 10000 ? 0 : 1)}k` : hfDownloads}
              </span>
            )}
            {hfLikes != null && (
              <span className="flex items-center gap-1" title="Likes">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
                </svg>
                {hfLikes >= 1000 ? `${(hfLikes / 1000).toFixed(hfLikes >= 10000 ? 0 : 1)}k` : hfLikes}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="border-t border-surface-300 pt-3 space-y-1">
        <div className="flex justify-between text-xs font-mono">
          <span className="text-surface-800">input</span>
          <span className="text-neutral-300">${costInput.toFixed(2)}/1M</span>
        </div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-surface-800">output</span>
          <span className="text-neutral-300">${costOutput.toFixed(2)}/1M</span>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-surface-300 flex items-center justify-between">
        <code className="text-[10px] font-mono text-surface-700 break-all">{slug}</code>
        {isAdmin && (status === "inactive" || status === "pending") && onDeploy && (
          <button
            onClick={() => onDeploy(id)}
            disabled={deploying}
            className="text-[10px] font-mono uppercase tracking-wider px-3 py-1 border text-terminal-400 border-terminal-800 bg-terminal-950/40 hover:bg-terminal-900/60 transition-colors disabled:opacity-40"
          >
            {deploying ? "Deploying..." : "Deploy"}
          </button>
        )}
      </div>
    </div>
  );
}
