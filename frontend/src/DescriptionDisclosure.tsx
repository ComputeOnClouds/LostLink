export const DESCRIPTION_DISCLOSURE = 'may be generated using Gen AI.';

export function DescriptionDisclosure({ id }: { id?: string }) {
  return <p id={id} className="description-disclosure">{DESCRIPTION_DISCLOSURE}</p>;
}

export function DescriptionBlock({ description }: { description: string | null | undefined }) {
  return (
    <div className="description-block">
      <div className="title">{description || '(photo-based item)'}</div>
      <DescriptionDisclosure />
    </div>
  );
}
