# Dagger versioned API schemas

| Built route | Upstream base | Candidate |
| --- | --- | --- |
| Released 1.0 beta Container reference | Shows `withMountedTemp.disk`, which is absent from the release schema | Correctly omits `disk` |
| Next Container reference | Shows `withMountedTemp.disk` | Still shows `disk` |
| New rolling archive from beta.27 | No archived SDL emitted | Archived SDL matches the selected Git tag byte for byte |

The docs generator now copies the schema from the same Git ref as the snapshot. Docusaurus chooses the model using the version of the page being rendered. The archived schemas match the seven source-release Git blobs in the provenance file.

Both revisions passed a frozen Yarn install and `yarn build`. An independent HTML check verified both Container reference pages. A separate live run used the checksum-verified Dagger beta.28 CLI to regenerate the rolling archive from beta.27 and verified the exported schema against its expected Git blob. Initial JavaScript on the released page grew from 384,179 to 495,358 gzip bytes because the client receives the archived models.

- Base `c1f8e9ae88f6c238ee02bef12ff131847052abc2`.
- Candidate `cca0d6fcf66848bacc5865bbcecd155a4979bbae`. [Commit](https://github.com/archit15singh/dagger/commit/cca0d6fcf66848bacc5865bbcecd155a4979bbae)
- [Exact Docusaurus builds and HTML](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44860859569) · [Exact CLI archive generation](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44861165004) · [Source-release provenance](dagger-14081-provenance.tsv)
- [Upstream issue](https://github.com/dagger/dagger/issues/14081)
